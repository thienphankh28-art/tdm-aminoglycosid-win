"""

tab1_aminoglycosid.py — Tab "Tính toán & TDM" cho Aminoglycosid (liều đầu tiên, cá thể hóa

Mục 3, hiệu chỉnh liều Mục 4, biểu đồ mô phỏng, xuất PDF).



Tách riêng khỏi app.py để phát triển/bảo trì độc lập với các tab khác (Vancomycin, CSDL...).

Toàn bộ logic tính toán PK vẫn nằm nguyên trong pk_calculations.py — file này CHỈ chứa UI.

"""



from tkinter import ttk, messagebox, filedialog

import json
import datetime
import customtkinter as ctk



from matplotlib.figure import Figure

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg



import database as db

from pk_calculations import (

    PatientInfo, MeasuredLevels,

    compute_bmi, compute_ibw, compute_dosing_weight,

    compute_total_dose,

    compute_ke_individual, compute_t_half_individual, compute_true_peak,

    compute_true_trough, compute_vd_individual,

    compute_predicted_cp_adjusted, compute_predicted_ctrough_adjusted,

    simulate_dosing_curve,

)

from ui_common import (
    FONT_H2, FONT_SMALL,
    parse_date, today_str, clean_vn_text, parse_float,
    LabeledEntry, LabeledOption, LabeledCheck, MetricCard, StatusLabel,
)
from amg_bayesian_calculations import (
    AmgPatientInfo, AmgDose, AmgMeasurement,
    compute_population_priors_amg, group_measurements_by_dose_block_amg,
    solve_bayesian_sequential_amg, find_nearest_scr_amg, recompute_cl_prior_amg,
    compute_css_peak_trough_amg, simulate_concentration_curve_amg,
)


def parse_amg_dt(value, default=None):
    """Parse chuỗi 'YYYY-MM-DD HH:MM' thành datetime.datetime. Lỗi -> default hoặc hiện tại."""
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except Exception:
            continue
    return default if default is not None else datetime.datetime.now()


class AmgDateTimePickerWindow(ctk.CTkToplevel):
    """Hộp thoại chọn ngày giờ dạng lịch trực quan (dùng chung cho các dòng liều/SCr/điểm đo)."""

    def __init__(self, parent, initial_dt=None, callback=None):
        super().__init__(parent)
        self.title("Chọn ngày và giờ")
        self.geometry("340x230")
        self.resizable(False, False)
        self.callback = callback
        self.dt = initial_dt or datetime.datetime.now()
        self.transient(parent)
        self.grab_set()

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        ctk.CTkLabel(frame, text="📅 Chọn thời điểm", font=FONT_H2).pack(anchor="w", pady=(0, 10))

        d_frame = ctk.CTkFrame(frame, fg_color="transparent")
        d_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(d_frame, text="Ngày (YYYY-MM-DD):", font=FONT_SMALL).pack(anchor="w")
        self.date_entry = ctk.CTkEntry(d_frame)
        self.date_entry.pack(fill="x", pady=(2, 8))
        self.date_entry.insert(0, self.dt.strftime("%Y-%m-%d"))

        t_frame = ctk.CTkFrame(frame, fg_color="transparent")
        t_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(t_frame, text="Giờ (HH:MM):", font=FONT_SMALL).pack(anchor="w")
        self.time_entry = ctk.CTkEntry(t_frame)
        self.time_entry.pack(fill="x", pady=(2, 16))
        self.time_entry.insert(0, self.dt.strftime("%H:%M"))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x")
        ctk.CTkButton(btn_frame, text="Xác nhận", fg_color="#2f6f4f", hover_color="#254f39",
                      command=self.confirm).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="Hủy", fg_color="gray", command=self.destroy).pack(side="right")

    def confirm(self):
        try:
            parsed = parse_amg_dt(f"{self.date_entry.get().strip()} {self.time_entry.get().strip()}")
            if self.callback:
                self.callback(parsed)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Định dạng ngày giờ không hợp lệ: {e}")


class AmgDoseRow(ctk.CTkFrame):
    """Một dòng liều dùng: Liều (mg) + τ (h) + Thời điểm bắt đầu + nút thêm liều tự động."""

    def __init__(self, master, on_remove, on_auto_add, dose_default=400.0, tau_default=24.0,
                 dt_default=None, **kwargs):
        super().__init__(master, fg_color=("gray95", "gray16"), corner_radius=6, **kwargs)
        dt_default = dt_default or datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        self.on_auto_add_callback = on_auto_add
        self.dose_var = ctk.StringVar(value=str(dose_default))
        self.tau_var = ctk.StringVar(value=str(tau_default))
        self.dt_var = ctk.StringVar(value=dt_default.strftime("%Y-%m-%d %H:%M"))

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=8, pady=6)
        self.seq_label = ctk.CTkLabel(grid, text="1.", font=FONT_SMALL, width=25, anchor="e")
        self.seq_label.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(grid, text="Liều (mg):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(grid, textvariable=self.dose_var, width=65).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(grid, text="τ (h):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(grid, textvariable=self.tau_var, width=45).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(grid, text="Bắt đầu:", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(grid, textvariable=self.dt_var, width=130).pack(side="left", padx=(0, 4))
        ctk.CTkButton(grid, text="📅", width=32, command=self.open_calendar).pack(side="left", padx=(0, 6))
        ctk.CTkButton(grid, text="➕ Tự động", width=75, fg_color="#1f6feb", hover_color="#1158c7",
                      command=lambda: self.on_auto_add_callback(self)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(grid, text="🗑", width=32, fg_color="#d1242f", hover_color="#a01c24",
                      command=lambda: on_remove(self)).pack(side="left")

    def set_seq(self, num):
        self.seq_label.configure(text=f"Liều {num}:")

    def open_calendar(self):
        AmgDateTimePickerWindow(self, initial_dt=parse_amg_dt(self.dt_var.get()),
                                 callback=lambda dt: self.dt_var.set(dt.strftime("%Y-%m-%d %H:%M")))

    def get_dose(self):
        return AmgDose(dose_mg=parse_float(self.dose_var.get(), 0.0), given_at=parse_amg_dt(self.dt_var.get()))

    def get_tau(self):
        return parse_float(self.tau_var.get(), 24.0)


class AmgScrRow(ctk.CTkFrame):
    """Một dòng nhập SCr: Giá trị SCr + ĐƠN VỊ (μmol/L hoặc mg/dL, người dùng tự chọn) +
    Thời điểm đo + nút xóa (hỗ trợ nhiều lần đo SCr)."""

    def __init__(self, master, on_remove, scr_default=80.0, unit_default="μmol/L", dt_default=None, **kwargs):
        super().__init__(master, fg_color=("gray95", "gray16"), corner_radius=6, **kwargs)
        dt_default = dt_default or datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        self.scr_var = ctk.StringVar(value=str(scr_default))
        self.unit_var = ctk.StringVar(value=unit_default)
        self.dt_var = ctk.StringVar(value=dt_default.strftime("%Y-%m-%d %H:%M"))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(row, text="SCr:", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.scr_var, width=60).pack(side="left", padx=(0, 4))
        ctk.CTkOptionMenu(row, values=["μmol/L", "mg/dL"], variable=self.unit_var, width=90
                           ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text="Thời điểm đo:", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.dt_var, width=130).pack(side="left", padx=(0, 4))
        ctk.CTkButton(row, text="📅", width=32, command=self.open_calendar).pack(side="left", padx=(0, 6))
        ctk.CTkButton(row, text="🗑", width=32, fg_color="#d1242f", hover_color="#a01c24",
                      command=lambda: on_remove(self)).pack(side="left")

    def open_calendar(self):
        AmgDateTimePickerWindow(self, initial_dt=parse_amg_dt(self.dt_var.get()),
                                 callback=lambda dt: self.dt_var.set(dt.strftime("%Y-%m-%d %H:%M")))

    def get_scr(self):
        """Trả về (SCr ĐÃ QUY ĐỔI mg/dL theo đơn vị người dùng chọn, thời điểm đo) — dùng
        trực tiếp cho tính toán, KHÔNG còn tự đoán đơn vị theo ngưỡng >10 nữa."""
        raw = parse_float(self.scr_var.get(), 0.0)
        scr_mgdl = raw / 88.4 if self.unit_var.get() == "μmol/L" else raw
        return scr_mgdl, parse_amg_dt(self.dt_var.get())

    def get_raw(self):
        """Trả về (giá trị SCr GỐC người dùng nhập, đơn vị đã chọn, thời điểm đo) — dùng khi
        lưu/tải lại để hiển thị đúng như người dùng đã nhập, không hiển thị số đã quy đổi."""
        return parse_float(self.scr_var.get(), 0.0), self.unit_var.get(), parse_amg_dt(self.dt_var.get())


class AmgMeasRow(ctk.CTkFrame):
    """Một dòng điểm đo: Cobs + Tobs + Tinf + nút xóa (hỗ trợ nhiều điểm đo)."""

    def __init__(self, master, on_remove, cobs_default=8.0, tinf_default=1.0, dt_default=None, **kwargs):
        super().__init__(master, fg_color=("gray95", "gray16"), corner_radius=6, **kwargs)
        dt_default = dt_default or datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        self.cobs_var = ctk.StringVar(value=str(cobs_default))
        self.dt_var = ctk.StringVar(value=dt_default.strftime("%Y-%m-%d %H:%M"))
        self.tinf_var = ctk.StringVar(value=str(tinf_default))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(row, text="Cobs (μg/mL):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.cobs_var, width=65).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text="Tobs:", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.dt_var, width=130).pack(side="left", padx=(0, 4))
        ctk.CTkButton(row, text="📅", width=32, command=self.open_calendar).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(row, text="Tinf (h):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.tinf_var, width=45).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="🗑", width=32, fg_color="#d1242f", hover_color="#a01c24",
                      command=lambda: on_remove(self)).pack(side="left")

    def open_calendar(self):
        AmgDateTimePickerWindow(self, initial_dt=parse_amg_dt(self.dt_var.get()),
                                 callback=lambda dt: self.dt_var.set(dt.strftime("%Y-%m-%d %H:%M")))

    def get_measurement(self):
        return AmgMeasurement(c_obs=parse_float(self.cobs_var.get(), 0.0),
                               t_obs=parse_amg_dt(self.dt_var.get()),
                               t_inf_h=parse_float(self.tinf_var.get(), 1.0))





class AmgNewDoseRow(ctk.CTkFrame):
    """Một tổ hợp (liều mới - τ mới - Tinf mới) để xem trước Cpeak/Ctrough dự đoán ở trạng
    thái ổn định, dựa trên CLpost/Vdpost/Ke vừa tối ưu Bayesian — tương đương các ô
    F12-F14/F18-F19 của Excel. Người dùng có thể thêm nhiều tổ hợp để so sánh."""

    def __init__(self, master, on_remove, on_compute, dose_default=400.0, tau_default=24.0,
                 tinf_default=1.0, **kwargs):
        super().__init__(master, fg_color=("gray95", "gray16"), corner_radius=6, **kwargs)
        self.dose_var = ctk.StringVar(value=str(dose_default))
        self.tau_var = ctk.StringVar(value=str(tau_default))
        self.tinf_var = ctk.StringVar(value=str(tinf_default))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(row, text="Liều mới (mg):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.dose_var, width=60).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text="τ mới (h):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.tau_var, width=45).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text="Tinf mới (h):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.tinf_var, width=45).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="🧮 Tính", width=65, command=lambda: on_compute(self)).pack(side="left", padx=(0, 8))
        self.result_label = ctk.CTkLabel(row, text="Cpeak: --   Ctrough: --", font=FONT_SMALL,
                                          text_color=("#0969da", "#58a6ff"))
        self.result_label.pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="🗑", width=32, fg_color="#d1242f", hover_color="#a01c24",
                      command=lambda: on_remove(self)).pack(side="left")

    def get_combo(self):
        return (parse_float(self.dose_var.get(), 0.0), parse_float(self.tau_var.get(), 24.0),
                parse_float(self.tinf_var.get(), 1.0))

    def set_result(self, cpeak, ctrough):
        self.result_label.configure(text=f"Cpeak: {cpeak:.2f} μg/mL   Ctrough: {ctrough:.2f} μg/mL")


class Tab1CalcFrame(ctk.CTkScrollableFrame):



    def __init__(self, master, app):



        super().__init__(master, fg_color="transparent")



        self.app = app







        # Trạng thái tính toán (tương đương st.session_state.sec3_calcs / sec4_calcs)



        self.sec3 = {"ke": 0.0, "thalf": 0.0, "vd": 0.0, "cp": 0.0, "ctr": 0.0, "calculated": False}



        self.sec4 = {"cp_pred": 0.0, "ctr_pred": 0.0}



        self.loaded_patient = None



        self.loaded_tdm = None







        self._build_lookup_section()



        self._build_section1_patient()
        self._build_amg_method_selector()

        # Container gộp Mục 2-6 (phương pháp Sawchuk-Zaske cũ) để có thể ẩn/hiện theo phương pháp
        self.sz_container = ctk.CTkFrame(self, fg_color="transparent")
        self.sz_container.pack(fill="x")

        self._build_section2_population()



        self._build_section3_individual()



        self._build_section4_adjustment()



        self._build_section5_chart()



        self._build_section6_pdf()

        # --- Container mới cho phương pháp Bayesian (Aréchiga-Alvarado 2020) — ẩn mặc định ---
        self.amg_dose_rows = []
        self.amg_scr_rows = []
        self.amg_meas_rows = []
        self.amg_newdose_rows = []
        self.amg_priors = None
        self.amg_bayes_result = None
        self.amg_block_results = []
        self.amg_chart_canvas = None
        self.bayes_container = ctk.CTkFrame(self, fg_color="transparent")
        self._build_amg_bayesian_sections()
        self.on_amg_method_change()

        self.recalc_population()







    # ---------------------------------------------------------------



    def _section_header(self, text, parent=None):
        ctk.CTkLabel(parent or self, text=text, font=FONT_H2).pack(anchor="w", padx=6, pady=(18, 6))







    # ---------------------------------------------------------------



    def _build_lookup_section(self):



        self._section_header("🔍 Truy xuất bệnh nhân từ Cloud")



        row = ctk.CTkFrame(self, fg_color="transparent")



        row.pack(fill="x", padx=6)



        self.lookup_entry = LabeledEntry(row, "Nhập MSYT để tự động điền dữ liệu")



        self.lookup_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))



        ctk.CTkButton(row, text="Tải dữ liệu bệnh nhân", width=170,



                      command=self.load_patient).pack(side="left", pady=(18, 4))



        self.lookup_status = StatusLabel(self)



        self.lookup_status.pack(fill="x", padx=6, pady=(4, 0))



        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=10)







    def load_patient(self):



        msyt = self.lookup_entry.get().strip()



        if not msyt:



            self.lookup_status.show("⚠️ Vui lòng nhập MSYT.", "warning")



            return



        p_data, t_data = db.get_latest_tdm(msyt)



        if p_data:



            self.loaded_patient = p_data



            self.loaded_tdm = t_data



            self.lookup_status.show(f"✅ Đã tải thành công bệnh nhân: {msyt}", "success")



            self._apply_loaded_defaults(msyt)



        else:



            self.loaded_patient = None



            self.loaded_tdm = None



            self.lookup_status.show("❌ Không tìm thấy MSYT trong Cloud CSDL.", "error")







    def _apply_loaded_defaults(self, lookup_msyt):



        p = self.loaded_patient or {}



        t = self.loaded_tdm or {}







        default_weight = float(p.get("weight", 70.0) or 70.0)



        default_height = float(p.get("height", 170.0) or 170.0)



        default_age = float(p.get("age", 50.0) or 50.0)







        default_dose_mg_kg = 5.3



        if t.get("new_dose") and default_weight > 0:



            default_dose_mg_kg = round(float(t.get("new_dose")) / default_weight, 2)







        self.msyt_entry.set(p.get("msyt", lookup_msyt))



        self.gender_opt.set(p.get("gender", "nam") if p.get("gender") in ("nam", "nữ") else "nam")



        self.weight_entry.set(default_weight)



        self.height_entry.set(default_height)



        self.age_entry.set(default_age)



        self.is_cf_check.set(bool(p.get("is_cf", True)))



        self.dose_mg_kg_entry.set(default_dose_mg_kg)



        self.infusion_time_entry.set(float(t.get("new_t_inf", 1.0) or 1.0))



        self.tau_entry.set(float(t.get("new_tau", 24.0) or 24.0))



        self.target_cp_entry.set(float(t.get("pred_cp", 20.0) or 20.0))



        self.target_ctr_entry.set(float(t.get("pred_ctrough", 1.0) or 1.0))







        self.current_scr_entry.set(float(t.get("scr", 80.0) or 80.0))



        self.t1_entry.set(float(t.get("t1", 3.0) or 3.0))



        self.c1_entry.set(float(t.get("c1", 17.5) or 17.5))



        self.t2_entry.set(float(t.get("t2", 17.0) or 17.0))



        self.c2_entry.set(float(t.get("c2", 4.8) or 4.8))







        self.recalc_population()







    # ---------------------------------------------------------------



    def _build_section1_patient(self):



        self._section_header("1. Thông tin bệnh nhân")



        grid = ctk.CTkFrame(self, fg_color="transparent")



        grid.pack(fill="x", padx=6)



        for i in range(3):



            grid.grid_columnconfigure(i, weight=1, uniform="col")







        c1 = ctk.CTkFrame(grid, fg_color="transparent")



        c1.grid(row=0, column=0, sticky="new", padx=(0, 10))



        self.msyt_entry = LabeledEntry(c1, "MSYT (Bắt buộc để lưu)")



        self.msyt_entry.pack(fill="x")



        self.gender_opt = LabeledOption(c1, "Giới tính", ["nam", "nữ"], default="nam")



        self.gender_opt.pack(fill="x")



        self.weight_entry = LabeledEntry(c1, "Cân nặng (kg)", default=70.0)



        self.weight_entry.pack(fill="x")



        self.height_entry = LabeledEntry(c1, "Chiều cao (cm)", default=170.0)



        self.height_entry.pack(fill="x")







        c2 = ctk.CTkFrame(grid, fg_color="transparent")



        c2.grid(row=0, column=1, sticky="new", padx=10)



        self.age_entry = LabeledEntry(c2, "Tuổi", default=50.0)



        self.age_entry.pack(fill="x")



        self.is_cf_check = LabeledCheck(c2, "Đối tượng: Xơ nang (Cystic Fibrosis)", default=True)



        self.is_cf_check.pack(fill="x", pady=(10, 0))







        c3 = ctk.CTkFrame(grid, fg_color="transparent")



        c3.grid(row=0, column=2, sticky="new", padx=(10, 0))



        self.dose_mg_kg_entry = LabeledEntry(c3, "Liều AG (mg/kg)", default=5.3)



        self.dose_mg_kg_entry.pack(fill="x")



        self.infusion_time_entry = LabeledEntry(c3, "Thời gian truyền ban đầu (h, t')", default=1.0)



        self.infusion_time_entry.pack(fill="x")



        self.tau_entry = LabeledEntry(c3, "Khoảng đưa liều hiện tại (h)", default=24.0)



        self.tau_entry.pack(fill="x")







        grid2 = ctk.CTkFrame(self, fg_color="transparent")



        grid2.pack(fill="x", padx=6, pady=(6, 0))



        grid2.grid_columnconfigure((0, 1), weight=1, uniform="col2")



        self.target_cp_entry = LabeledEntry(grid2, "Cp kỳ vọng (μg/mL)", default=20.0)



        self.target_cp_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))



        self.target_ctr_entry = LabeledEntry(grid2, "Ctr kỳ vọng (μg/mL)", default=1.0)



        self.target_ctr_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))







        # Tự động cập nhật Mục 2 (thông số quần thể) khi các trường liên quan thay đổi



        for widget in (self.weight_entry, self.height_entry, self.age_entry, self.dose_mg_kg_entry):



            widget.var.trace_add("write", lambda *a: self.recalc_population())



        self.gender_opt.var.trace_add("write", lambda *a: self.recalc_population())



        self.is_cf_check.var.trace_add("write", lambda *a: self.recalc_population())







        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)







    # ---------------------------------------------------------------



    def _build_section2_population(self):



        self._section_header("2. Thông số quần thể tham khảo", parent=self.sz_container)



        row = ctk.CTkFrame(self.sz_container, fg_color="transparent")



        row.pack(fill="x", padx=6)



        row.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="m")



        self.card_bmi = MetricCard(row, "BMI")



        self.card_bmi.grid(row=0, column=0, sticky="ew", padx=4, pady=4)



        self.card_ibw = MetricCard(row, "IBW (kg)")



        self.card_ibw.grid(row=0, column=1, sticky="ew", padx=4, pady=4)



        self.card_dosing_w = MetricCard(row, "Cân nặng tính liều (kg)")



        self.card_dosing_w.grid(row=0, column=2, sticky="ew", padx=4, pady=4)



        self.card_total_dose = MetricCard(row, "Tổng liều lý thuyết (mg)")



        self.card_total_dose.grid(row=0, column=3, sticky="ew", padx=4, pady=4)



        ttk.Separator(self.sz_container, orient="horizontal").pack(fill="x", padx=6, pady=14)







    def _get_patient_info(self):



        return PatientInfo(



            gender=self.gender_opt.get(),



            height_cm=self.height_entry.get_float(170.0),



            weight_kg=self.weight_entry.get_float(70.0),



            scr_umol=100.0,



            age=self.age_entry.get_float(50.0),



            is_cf=self.is_cf_check.get(),



        )







    def recalc_population(self):



        patient = self._get_patient_info()



        bmi = compute_bmi(patient)



        ibw = compute_ibw(patient)



        dosing_weight = compute_dosing_weight(patient, ibw)



        total_dose = compute_total_dose(self.dose_mg_kg_entry.get_float(5.3), dosing_weight)







        self.card_bmi.set_value(f"{bmi:.2f}")



        self.card_ibw.set_value(f"{ibw:.2f}")



        self.card_dosing_w.set_value(f"{dosing_weight:.2f}")



        self.card_total_dose.set_value(f"{total_dose:.1f}")







        self._bmi, self._ibw, self._dosing_weight, self._total_dose = bmi, ibw, dosing_weight, total_dose



        # Đồng bộ "Tổng liều đã dùng khi lấy mẫu" nếu chưa được người dùng chỉnh sửa thủ công



        if hasattr(self, "dose_given_entry") and not getattr(self, "_dose_given_touched", False):



            self.dose_given_entry.set(round(total_dose, 2))



        if hasattr(self, "tau_sampling_entry") and not getattr(self, "_tau_sampling_touched", False):



            self.tau_sampling_entry.set(self.tau_entry.get_float(24.0))







    # ---------------------------------------------------------------



    def _build_section3_individual(self):



        self._section_header("3. Cá thể hoá theo kết quả TDM", parent=self.sz_container)



        row1 = ctk.CTkFrame(self.sz_container, fg_color="transparent")



        row1.pack(fill="x", padx=6)



        row1.grid_columnconfigure((0, 1), weight=1, uniform="s3a")



        self.tdm_date_entry = LabeledEntry(row1, "Ngày thực hiện TDM (YYYY-MM-DD)", default=today_str())



        self.tdm_date_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))



        self.current_scr_entry = LabeledEntry(row1, "Scr ngày TDM (μmol/L)", default=80.0)



        self.current_scr_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))







        self.is_first_dose_check = LabeledCheck(self.sz_container, "Liều ĐẦU TIÊN (chưa tích luỹ)", default=False)



        self.is_first_dose_check.pack(anchor="w", padx=6, pady=(4, 0))







        self.dose_given_entry = LabeledEntry(self.sz_container, "Tổng liều đã dùng khi lấy mẫu (mg)", default=0.0)



        self.dose_given_entry.pack(fill="x", padx=6)



        self.dose_given_entry.var.trace_add("write", lambda *a: setattr(self, "_dose_given_touched", True))







        self.tau_sampling_entry = LabeledEntry(self.sz_container, "Khoảng đưa liều (τ) lúc lấy mẫu (h)", default=24.0)



        self.tau_sampling_entry.pack(fill="x", padx=6)



        self.tau_sampling_entry.var.trace_add("write", lambda *a: setattr(self, "_tau_sampling_touched", True))







        row2 = ctk.CTkFrame(self.sz_container, fg_color="transparent")



        row2.pack(fill="x", padx=6, pady=(4, 0))



        row2.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="s3b")



        self.t1_entry = LabeledEntry(row2, "T1 (h, từ lúc truyền)", default=3.0)



        self.t1_entry.grid(row=0, column=0, sticky="ew", padx=4)



        self.c1_entry = LabeledEntry(row2, "C1 (μg/mL)", default=17.5)



        self.c1_entry.grid(row=0, column=1, sticky="ew", padx=4)



        self.t2_entry = LabeledEntry(row2, "T2 (h, từ lúc truyền)", default=17.0)



        self.t2_entry.grid(row=0, column=2, sticky="ew", padx=4)



        self.c2_entry = LabeledEntry(row2, "C2 (μg/mL)", default=4.8)



        self.c2_entry.grid(row=0, column=3, sticky="ew", padx=4)







        ctk.CTkButton(self.sz_container, text="🧮 TÍNH TOÁN CÁ THỂ HÓA", height=36,
                      command=self.calc_section3).pack(fill="x", padx=6, pady=(12, 6))
        self.sec3_status = StatusLabel(self.sz_container)



        self.sec3_status.pack(fill="x", padx=6)







        row3 = ctk.CTkFrame(self.sz_container, fg_color="transparent")



        row3.pack(fill="x", padx=6, pady=(8, 0))



        row3.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="i")



        self.card_ke = MetricCard(row3, "Ke cá thể (h⁻¹)")



        self.card_ke.grid(row=0, column=0, sticky="ew", padx=4, pady=4)



        self.card_thalf = MetricCard(row3, "T1/2 cá thể (h)")



        self.card_thalf.grid(row=0, column=1, sticky="ew", padx=4, pady=4)



        self.card_vd = MetricCard(row3, "Vd cá thể (L)")



        self.card_vd.grid(row=0, column=2, sticky="ew", padx=4, pady=4)



        self.card_cp = MetricCard(row3, "Cp thật (μg/mL)")



        self.card_cp.grid(row=0, column=3, sticky="ew", padx=4, pady=4)



        self.card_ctr = MetricCard(row3, "Ctrough thật (μg/mL)")



        self.card_ctr.grid(row=0, column=4, sticky="ew", padx=4, pady=4)







        ctk.CTkButton(self.sz_container, text="💾 Xác nhận & Lưu lên Cloud (Mục 3)", height=36,
                      fg_color="#2f6f4f", hover_color="#254f39",
                      command=self.save_section3).pack(fill="x", padx=6, pady=(12, 4))
        self.save3_status = StatusLabel(self.sz_container)



        self.save3_status.pack(fill="x", padx=6)







        ttk.Separator(self.sz_container, orient="horizontal").pack(fill="x", padx=6, pady=14)







    def calc_section3(self):



        t1_h = self.t1_entry.get_float()



        c1_val = self.c1_entry.get_float()



        t2_h = self.t2_entry.get_float()



        c2_val = self.c2_entry.get_float()



        infusion_time_h = self.infusion_time_entry.get_float(1.0)



        tau_at_sampling_h = self.tau_sampling_entry.get_float(24.0)



        dose_given_mg = self.dose_given_entry.get_float()



        is_first_dose = self.is_first_dose_check.get()







        if t2_h <= t1_h or c1_val <= 0 or c2_val <= 0 or c1_val <= c2_val:



            self.sec3_status.show("⚠️ Dữ liệu T/C không hợp lệ.", "error")



            self.sec3["calculated"] = False



            return







        measured = MeasuredLevels(is_first_dose, t1_h, c1_val, t2_h, c2_val,



                                   infusion_time_h, tau_at_sampling_h, dose_given_mg)



        ke_ind = compute_ke_individual(measured)



        t_half_ind = compute_t_half_individual(ke_ind)



        true_peak = compute_true_peak(measured, ke_ind)



        true_trough = compute_true_trough(true_peak, ke_ind, infusion_time_h, tau_at_sampling_h)



        vd_ind = compute_vd_individual(dose_given_mg, ke_ind, true_peak, infusion_time_h,



                                        tau_at_sampling_h, is_first_dose)







        self.sec3 = {"ke": ke_ind, "thalf": t_half_ind, "vd": vd_ind,



                     "cp": true_peak, "ctr": true_trough, "calculated": True}



        self._refresh_sec3_cards()



        self.sec3_status.show("✅ Đã tính toán cá thể hóa thành công.", "success")







    def _refresh_sec3_cards(self):



        c = self.sec3



        self.card_ke.set_value(f"{c['ke']:.4f}")



        self.card_thalf.set_value(f"{c['thalf']:.2f}")



        self.card_vd.set_value(f"{c['vd']:.2f}")



        self.card_cp.set_value(f"{c['cp']:.2f}")



        self.card_ctr.set_value(f"{c['ctr']:.3f}")







    def save_section3(self):



        msyt_input = self.msyt_entry.get().strip()



        if not msyt_input:



            self.save3_status.show("⚠️ Vui lòng nhập MSYT ở Mục 1.", "error")



            return



        if not self.sec3["calculated"]:



            self.save3_status.show("⚠️ Vui lòng nhấn nút 'Tính toán' trước khi lưu.", "warning")



            return







        tdm_date = parse_date(self.tdm_date_entry.get())



        date_str = tdm_date.strftime("%Y-%m-%d")







        def do_save():



            ok_info, msg_info = db.save_patient_info(



                msyt_input, self.gender_opt.get(), self.weight_entry.get_float(),



                self.height_entry.get_float(), self.age_entry.get_float(),



                int(self.is_cf_check.get()))



            if not ok_info:



                self.save3_status.show(f"❌ {msg_info}", "error")



                return



            c = self.sec3



            ok_tdm, msg_tdm = db.save_sec3_data(



                msyt_input, date_str, self.current_scr_entry.get_float(),



                self.t1_entry.get_float(), self.c1_entry.get_float(),



                self.t2_entry.get_float(), self.c2_entry.get_float(),



                c["ke"], c["thalf"], c["vd"], c["cp"], c["ctr"])



            self.save3_status.show(("✅ " if ok_tdm else "❌ ") + msg_tdm, "success" if ok_tdm else "error")







        if db.check_tdm_exists(msyt_input, date_str):



            if messagebox.askyesno("Xác nhận ghi đè",



                                    f"⚠️ Kết quả TDM ngày {tdm_date.strftime('%d/%m/%Y')} đã tồn tại "



                                    f"trên Cloud. Bạn có muốn ghi đè?"):



                do_save()



            else:



                self.save3_status.show("Đã hủy thao tác lưu.", "info")



        else:



            do_save()







    # ---------------------------------------------------------------



    def _build_section4_adjustment(self):



        self._section_header("4. Hiệu chỉnh liều theo TDM", parent=self.sz_container)



        row = ctk.CTkFrame(self.sz_container, fg_color="transparent")



        row.pack(fill="x", padx=6)



        row.grid_columnconfigure((0, 1, 2), weight=1, uniform="s4")



        self.new_dose_entry = LabeledEntry(row, "Liều mới - Dose (mg)", default=400.0)



        self.new_dose_entry.grid(row=0, column=0, sticky="ew", padx=4)



        self.new_tau_entry = LabeledEntry(row, "Khoảng đưa liều mới - τ (h)", default=36.0)



        self.new_tau_entry.grid(row=0, column=1, sticky="ew", padx=4)



        self.new_t_inf_entry = LabeledEntry(row, "Thời gian truyền mới - t' (h)", default=1.0)



        self.new_t_inf_entry.grid(row=0, column=2, sticky="ew", padx=4)







        ctk.CTkButton(self.sz_container, text="🧮 TÍNH TOÁN LIỀU MỚI", height=36,
                      command=self.calc_section4).pack(fill="x", padx=6, pady=(12, 6))
        self.sec4_status = StatusLabel(self.sz_container)



        self.sec4_status.pack(fill="x", padx=6)







        row2 = ctk.CTkFrame(self.sz_container, fg_color="transparent")



        row2.pack(fill="x", padx=6, pady=(8, 0))



        row2.grid_columnconfigure((0, 1), weight=1, uniform="n")



        self.card_cp_pred = MetricCard(row2, "C'p dự đoán SS (μg/mL)")



        self.card_cp_pred.grid(row=0, column=0, sticky="ew", padx=4, pady=4)



        self.card_ctr_pred = MetricCard(row2, "C'tr dự đoán SS (μg/mL)")



        self.card_ctr_pred.grid(row=0, column=1, sticky="ew", padx=4, pady=4)







        ctk.CTkButton(self.sz_container, text="💾 Xác nhận & Lưu lên Cloud (Mục 4)", height=36,
                      fg_color="#2f6f4f", hover_color="#254f39",
                      command=self.save_section4).pack(fill="x", padx=6, pady=(12, 4))
        self.save4_status = StatusLabel(self.sz_container)



        self.save4_status.pack(fill="x", padx=6)







        ttk.Separator(self.sz_container, orient="horizontal").pack(fill="x", padx=6, pady=14)







    def calc_section4(self):



        if not self.sec3["calculated"]:



            self.sec4_status.show("❌ Bạn phải thực hiện Tính toán Mục 3 trước!", "error")



            return



        new_dose_mg = self.new_dose_entry.get_float()



        new_tau_h = self.new_tau_entry.get_float()



        new_t_inf_h = self.new_t_inf_entry.get_float()



        c = self.sec3



        cp_new = compute_predicted_cp_adjusted(new_dose_mg, c["ke"], c["vd"], new_t_inf_h, new_tau_h)



        ctrough_new = compute_predicted_ctrough_adjusted(cp_new, c["ke"], new_t_inf_h, new_tau_h)



        self.sec4 = {"cp_pred": cp_new, "ctr_pred": ctrough_new}



        self.card_cp_pred.set_value(f"{cp_new:.2f}")



        self.card_ctr_pred.set_value(f"{ctrough_new:.3f}")



        self.sec4_status.show("✅ Đã tính toán liều mới thành công.", "success")



        self.refresh_chart()







    def save_section4(self):



        msyt_input = self.msyt_entry.get().strip()



        if not msyt_input:



            self.save4_status.show("⚠️ Vui lòng nhập MSYT.", "error")



            return



        if self.sec4["cp_pred"] == 0:



            self.save4_status.show("⚠️ Vui lòng nhấn nút 'Tính toán liều mới' trước.", "warning")



            return







        tdm_date = parse_date(self.tdm_date_entry.get())



        date_str = tdm_date.strftime("%Y-%m-%d")



        new_dose_mg = self.new_dose_entry.get_float()



        new_tau_h = self.new_tau_entry.get_float()



        new_t_inf_h = self.new_t_inf_entry.get_float()



        s4 = self.sec4







        def do_save():



            ok, msg = db.save_sec4_data(msyt_input, date_str, new_dose_mg, new_tau_h, new_t_inf_h,



                                         s4["cp_pred"], s4["ctr_pred"])



            self.save4_status.show(("✅ " if ok else "❌ ") + msg, "success" if ok else "error")







        existing_block = db.get_specific_tdm_block(msyt_input, date_str)



        if existing_block and existing_block.get("new_dose") is not None:



            if messagebox.askyesno("Xác nhận ghi đè",



                                    f"⚠️ Block ngày {tdm_date.strftime('%d/%m/%Y')} đã có phác đồ. "



                                    f"Bạn có muốn ghi đè?"):



                do_save()



            else:



                self.save4_status.show("Đã hủy thao tác lưu.", "info")



        else:



            do_save()







    # ---------------------------------------------------------------



    def _build_section5_chart(self):



        self._section_header("5. Đồ thị nồng độ qua nhiều chu kỳ liều", parent=self.sz_container)



        row = ctk.CTkFrame(self.sz_container, fg_color="transparent")



        row.pack(fill="x", padx=6)



        ctk.CTkLabel(row, text="Số chu kỳ:", font=FONT_SMALL).pack(side="left", padx=(0, 10))



        self.num_cycles_var = ctk.IntVar(value=10)



        self.num_cycles_label = ctk.CTkLabel(row, text="10", font=FONT_SMALL, width=30)



        slider = ctk.CTkSlider(row, from_=2, to=20, number_of_steps=18,



                                variable=self.num_cycles_var, command=self._on_slider_change)



        slider.pack(side="left", fill="x", expand=True, padx=(0, 10))



        self.num_cycles_label.pack(side="left")







        self.chart_container = ctk.CTkFrame(self.sz_container, fg_color=("gray95", "gray14"), corner_radius=10)



        self.chart_container.pack(fill="both", padx=6, pady=(10, 6))



        self.chart_placeholder = ctk.CTkLabel(



            self.chart_container,



            text="Biểu đồ sẽ xuất hiện sau khi bạn hoàn thành Mục 3 và Mục 4.",



            font=FONT_SMALL, text_color=("gray40", "gray70"))



        self.chart_placeholder.pack(padx=20, pady=60)



        self.chart_canvas = None







        ttk.Separator(self.sz_container, orient="horizontal").pack(fill="x", padx=6, pady=14)







    def _on_slider_change(self, value):



        self.num_cycles_label.configure(text=str(int(round(value))))



        self.refresh_chart()







    def refresh_chart(self):



        c = self.sec3



        s4 = self.sec4



        if not (c["calculated"] and s4["cp_pred"] > 0):



            return







        num_cycles = int(round(self.num_cycles_var.get()))



        sim_times, sim_concs = simulate_dosing_curve(



            ke=c["ke"], vd=c["vd"],



            t_inf_old=self.infusion_time_entry.get_float(1.0),



            tau_old=self.tau_sampling_entry.get_float(24.0),



            peak_1=c["cp"], trough_1=c["ctr"],



            dose_new=self.new_dose_entry.get_float(),



            tau_new=self.new_tau_entry.get_float(),



            t_inf_new=self.new_t_inf_entry.get_float(),



            num_cycles=num_cycles,



        )



        target_cp = self.target_cp_entry.get_float(20.0)



        target_ctrough = self.target_ctr_entry.get_float(1.0)







        if self.chart_canvas is None:



            self.chart_placeholder.pack_forget()



            fig = Figure(figsize=(7.5, 4.2), dpi=100)



            self.chart_ax = fig.add_subplot(111)



            self.chart_canvas = FigureCanvasTkAgg(fig, master=self.chart_container)



            self.chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)







        ax = self.chart_ax



        ax.clear()



        ax.plot(sim_times, sim_concs, color="#1f77b4", linewidth=2, label="Nồng độ dự đoán C(t)")



        ax.axhline(y=target_cp, linestyle="--", color="green",



                   label=f"Cp kỳ vọng ({target_cp:g})")



        ax.axhline(y=target_ctrough, linestyle="--", color="orange",



                   label=f"Ctr kỳ vọng ({target_ctrough:g})")



        ax.set_xlabel("Thời gian (giờ)")



        ax.set_ylabel("Nồng độ (μg/mL)")



        ax.legend(loc="upper right", fontsize=8)



        ax.grid(alpha=0.25)



        self.chart_canvas.draw()







    # ---------------------------------------------------------------



    def _build_section6_pdf(self):



        ctk.CTkLabel(self.sz_container, text="📄 Xuất báo cáo hội chẩn TDM (PDF) theo CSDL bệnh nhân",



                     font=FONT_H2).pack(anchor="w", padx=6, pady=(4, 6))



        ctk.CTkButton(self.sz_container, text="📥 Tạo và Lưu file báo cáo PDF từ CSDL", height=36,



                      command=self.export_pdf).pack(fill="x", padx=6, pady=(0, 4))



        self.pdf_status = StatusLabel(self.sz_container)



        self.pdf_status.pack(fill="x", padx=6, pady=(0, 20))







    def export_pdf(self):



        msyt_input = self.msyt_entry.get().strip()



        if not msyt_input:



            self.pdf_status.show("⚠️ Vui lòng nhập MSYT để xuất báo cáo.", "error")



            return



        try:



            from fpdf import FPDF



        except ImportError:



            self.pdf_status.show("❌ Thiếu thư viện fpdf. Cài đặt bằng: pip install fpdf2", "error")



            return







        save_path = filedialog.asksaveasfilename(



            defaultextension=".pdf",



            initialfile=f"Bao_cao_CSDL_{msyt_input}.pdf",



            filetypes=[("PDF files", "*.pdf")],



        )



        if not save_path:



            return







        try:



            # 1. Truy vấn thông tin hành chính từ bảng 'patients' trên Supabase



            patient_res = db.supabase.table("patients").select("*").eq("msyt", msyt_input).execute()



            patient_info = patient_res.data[0] if patient_res.data else {}







            p_age = patient_info.get("age") or self.age_entry.get_float()



            p_gender = patient_info.get("gender") or self.gender_opt.get()



            p_weight = patient_info.get("weight_kg") or self.weight_entry.get_float()



            p_height = patient_info.get("height_cm") or self.height_entry.get_float()



            p_bmi = patient_info.get("bmi") or self._bmi



            p_ibw = patient_info.get("ibw") or self._ibw



            p_dosing_weight = patient_info.get("dosing_weight") or self._dosing_weight







            # 2. Truy vấn toàn bộ lịch sử TDM từ bảng 'tdm_history' trên Supabase



            history_res = (db.supabase.table("tdm_history").select("*")



                           .eq("msyt", msyt_input).order("tdm_date", desc=True).execute())



            records = history_res.data if history_res.data else []







            pdf = FPDF()



            pdf.add_page()







            pdf.set_font("Arial", "B", 14)



            pdf.cell(0, 10, clean_vn_text("BAO CAO LICH SU THEO DOI NONG DO THUOC (TDM) AMINOGLYCOSID"),



                     ln=True, align="C")



            pdf.ln(5)







            pdf.set_font("Arial", "B", 11)



            pdf.cell(0, 8, clean_vn_text("1. Thong tin hanh chinh benh nhan"), ln=True)



            pdf.set_font("Arial", "", 10)



            pdf.cell(0, 6, clean_vn_text(f"- Ma so y te (MSYT): {msyt_input}"), ln=True)



            pdf.cell(0, 6, clean_vn_text(



                f"- Tuoi: {p_age}   |   Gioi tinh: {p_gender}   |   Can nang: {p_weight} kg   |   "



                f"Chieu cao: {p_height} cm"), ln=True)



            pdf.cell(0, 6, clean_vn_text(



                f"- Chi so nhan: BMI = {p_bmi:.2f} kg/m2, IBW = {p_ibw:.2f} kg, "



                f"Can nang tinh lieu = {p_dosing_weight:.2f} kg"), ln=True)



            pdf.ln(5)







            pdf.set_font("Arial", "B", 11)



            if records:



                pdf.cell(0, 8, clean_vn_text(



                    f"2. Chi tiet cac dot TDM da thuc hien ({len(records)} ban ghi tu CSDL)"), ln=True)







                for idx, row in enumerate(records, 1):



                    ke_val = row.get("ke") or row.get("Ke") or 0



                    thalf_val = row.get("thalf") or row.get("t_half") or (0.693 / ke_val if ke_val > 0 else 0)



                    vd_val = row.get("vd") or row.get("Vd") or 0



                    peak_val = row.get("true_peak") or row.get("peak") or 0



                    trough_val = row.get("true_trough") or row.get("trough") or 0



                    dose_val = row.get("new_dose") or row.get("dose") or 0



                    tau_val = row.get("new_tau") or row.get("tau") or 24



                    t_inf_val = row.get("new_t_inf") or row.get("t_inf") or 1



                    cp_pred_val = row.get("cp_pred") or row.get("cp_predicted") or 0



                    ctr_pred_val = row.get("ctr_pred") or row.get("ctr_predicted") or 0







                    pdf.set_font("Arial", "B", 10)



                    pdf.cell(0, 6, clean_vn_text(



                        f"--- Dot {idx} | Ngay TDM: {row.get('tdm_date', 'Chua cap nhat')} ---"), ln=True)







                    pdf.set_font("Arial", "", 10)



                    pdf.cell(0, 5, clean_vn_text(



                        f"  + Duoc dong hoc (PK): Ke = {ke_val:.4f} h-1, t1/2 = {thalf_val:.2f} gio, "



                        f"Vd = {vd_val:.2f} lit"), ln=True)



                    pdf.cell(0, 5, clean_vn_text(



                        f"  + Nong do thuc te: Peak = {peak_val:.2f} ug/mL, Trough = {trough_val:.3f} ug/mL"),



                        ln=True)



                    pdf.cell(0, 5, clean_vn_text(



                        f"  + Khuyen nghi lieu moi: {dose_val} mg (tau = {tau_val}h, t' = {t_inf_val}h)"),



                        ln=True)



                    pdf.cell(0, 5, clean_vn_text(



                        f"  + Du doan tai CSS: Cp_pred = {cp_pred_val:.2f} ug/mL, "



                        f"Ctr_pred = {ctr_pred_val:.3f} ug/mL"), ln=True)



                    pdf.ln(3)



            else:



                pdf.set_font("Arial", "", 10)



                pdf.cell(0, 6, clean_vn_text("Chua co lich su TDM nao trong CSDL cho MSYT nay."), ln=True)







            pdf.ln(5)



            pdf.set_font("Arial", "I", 10)



            pdf.cell(100, 6, "", ln=0)



            pdf.cell(90, 6, clean_vn_text(f"Ngay lap bao cao: {datetime.date.today().strftime('%d/%m/%Y')}"),



                     ln=True, align="C")



            pdf.cell(100, 6, "", ln=0)



            pdf.cell(90, 6, clean_vn_text("Bac si / Duoc si lam sang"), ln=True, align="C")







            pdf.output(save_path)



            self.pdf_status.show(f"✅ Đã tạo báo cáo PDF thành công: {save_path}", "success")



        except Exception as e:



            self.pdf_status.show(f"❌ Lỗi khi tạo file PDF từ CSDL: {e}", "error")

    # =================================================================
    # PHƯƠNG PHÁP BAYESIAN — MÔ HÌNH ARÉCHIGA-ALVARADO 2020
    # (hoàn toàn tách biệt khỏi Sawchuk-Zaske ở trên; dùng chung Mục 1 - Thông tin bệnh nhân)
    # =================================================================
    def _build_amg_method_selector(self):
        ctk.CTkLabel(self, text="⚙️ Phương pháp tính TDM", font=FONT_H2).pack(anchor="w", padx=6, pady=(18, 4))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=(0, 4))
        ctk.CTkLabel(row, text="Phương pháp:", font=FONT_SMALL).pack(side="left", padx=(0, 8))
        self.amg_method_var = ctk.StringVar(value="Sawchuk-Zaske")
        ctk.CTkOptionMenu(row, values=["Sawchuk-Zaske", "Bayesian"], variable=self.amg_method_var,
                           width=160, command=self.on_amg_method_change).pack(side="left", padx=(0, 16))

        # Khung chọn "Mô hình Bayesian" — CHỈ hiện khi phương pháp = Bayesian (ẩn hoàn toàn khi Sawchuk-Zaske)
        self.amg_model_row = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self.amg_model_row, text="Mô hình Bayesian:", font=FONT_SMALL).pack(side="left", padx=(0, 8))
        self.amg_model_var = ctk.StringVar(value="Aréchiga-Alvarado 2020")
        ctk.CTkOptionMenu(self.amg_model_row, values=["Aréchiga-Alvarado 2020"], variable=self.amg_model_var,
                           width=210).pack(side="left")
        self.amg_model_note = ctk.CTkLabel(
            self, text="(Các mô hình Bayesian khác sẽ được cập nhật sau)", font=FONT_SMALL,
            text_color=("gray45", "gray65"))
        self.amg_method_separator = ttk.Separator(self, orient="horizontal")
        self.amg_method_separator.pack(fill="x", padx=6, pady=(4, 4))

    def on_amg_method_change(self, choice=None):
        if self.amg_method_var.get() == "Bayesian":
            self.sz_container.pack_forget()
            self.amg_model_row.pack(fill="x", padx=6, pady=(0, 4), before=self.amg_method_separator)
            self.amg_model_note.pack(anchor="w", padx=6, pady=(0, 8), before=self.amg_method_separator)
            self.bayes_container.pack(fill="x")
        else:
            self.bayes_container.pack_forget()
            self.amg_model_note.pack_forget()
            self.amg_model_row.pack_forget()
            self.sz_container.pack(fill="x")

    def _get_amg_patient(self):
        """Dùng chung thông tin bệnh nhân ở Mục 1 (tuổi/giới/cao/nặng) — SCr lấy đại diện
        từ danh sách nhiều lần đo SCr riêng của Bayesian (Mục B)."""
        return AmgPatientInfo(
            age=self.age_entry.get_float(50.0), gender=self.gender_opt.get(),
            height_cm=self.height_entry.get_float(170.0), weight_kg=self.weight_entry.get_float(70.0),
            scr_value=self._get_amg_representative_scr(),
        )

    def _build_amg_bayesian_sections(self):
        p = self.bayes_container
        ctk.CTkLabel(p, text="💊 TDM Bayesian — Mô hình Aréchiga-Alvarado 2020 (1 ngăn)", font=FONT_H2
                     ).pack(anchor="w", padx=6, pady=(6, 4))
        ctk.CTkLabel(p, text="Dùng chung Tuổi/Giới/Cân nặng/Chiều cao ở Mục 1 phía trên.",
                     font=FONT_SMALL, text_color=("gray40", "gray70")).pack(anchor="w", padx=6, pady=(0, 10))

        # --- B. Nhiều lần đo SCr ---
        ctk.CTkLabel(p, text="B. Các lần đo SCr", font=FONT_SMALL, text_color=("gray30", "gray80")
                     ).pack(anchor="w", padx=6, pady=(4, 4))
        ctk.CTkLabel(p, text="Chọn đúng đơn vị SCr cho từng dòng — phần mềm quy đổi tự động sang mg/dL để tính toán.",
                     font=FONT_SMALL, text_color=("gray45", "gray65")).pack(anchor="w", padx=6, pady=(0, 4))
        self.amg_scr_container = ctk.CTkFrame(p, fg_color="transparent")
        self.amg_scr_container.pack(fill="x", padx=6)
        ctk.CTkButton(p, text="➕ Thêm lần đo SCr", height=30, width=150,
                      command=lambda: self._add_amg_scr_row()).pack(anchor="w", padx=6, pady=(6, 4))
        ttk.Separator(p, orient="horizontal").pack(fill="x", padx=6, pady=14)

        # --- C. Lịch sử liều dùng ---
        ctk.CTkLabel(p, text="C. Lịch sử liều dùng (Truyền TM)", font=FONT_SMALL, text_color=("gray30", "gray80")
                     ).pack(anchor="w", padx=6, pady=(4, 4))
        self.amg_doses_container = ctk.CTkFrame(p, fg_color="transparent")
        self.amg_doses_container.pack(fill="x", padx=6)
        ctk.CTkButton(p, text="➕ Thêm liều thủ công", height=30, width=150,
                      command=lambda: self._add_amg_dose_row()).pack(anchor="w", padx=6, pady=(6, 4))
        ttk.Separator(p, orient="horizontal").pack(fill="x", padx=6, pady=14)

        # --- D. Nhiều điểm đo Cobs ---
        ctk.CTkLabel(p, text="D. Nồng độ đo được (nhiều điểm)", font=FONT_SMALL, text_color=("gray30", "gray80")
                     ).pack(anchor="w", padx=6, pady=(4, 4))
        self.amg_meas_container = ctk.CTkFrame(p, fg_color="transparent")
        self.amg_meas_container.pack(fill="x", padx=6)
        ctk.CTkButton(p, text="➕ Thêm điểm đo", height=30, width=140,
                      command=lambda: self._add_amg_meas_row()).pack(anchor="w", padx=6, pady=(6, 4))
        ttk.Separator(p, orient="horizontal").pack(fill="x", padx=6, pady=14)

        # --- E. Tối ưu Bayesian ---
        ctk.CTkLabel(p, text="E. Chạy tối ưu Bayesian", font=FONT_SMALL, text_color=("gray30", "gray80")
                     ).pack(anchor="w", padx=6, pady=(4, 6))
        ctk.CTkButton(p, text="🧮 CHẠY TỐI ƯU BAYESIAN", height=38, fg_color="#8250df", hover_color="#6639ba",
                      command=self.run_amg_bayes_solve).pack(fill="x", padx=6, pady=(0, 6))
        self.amg_solve_status = StatusLabel(p)
        self.amg_solve_status.pack(fill="x", padx=6)

        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=(8, 0))
        row.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="ares")
        self.amg_card_cl = MetricCard(row, "CL_post (L/h)")
        self.amg_card_cl.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.amg_card_vd = MetricCard(row, "Vd_post (L)")
        self.amg_card_vd.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.amg_card_ke = MetricCard(row, "Ke (h⁻¹)")
        self.amg_card_ke.grid(row=0, column=2, sticky="ew", padx=4, pady=4)
        self.amg_card_ofv = MetricCard(row, "OFV_final")
        self.amg_card_ofv.grid(row=0, column=3, sticky="ew", padx=4, pady=4)

        row2 = ctk.CTkFrame(p, fg_color="transparent")
        row2.pack(fill="x", padx=6, pady=(4, 0))
        row2.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="ares2")
        self.amg_card_cpeak = MetricCard(row2, "Cpeak hiện tại (μg/mL)")
        self.amg_card_cpeak.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.amg_card_ctrough = MetricCard(row2, "Ctrough hiện tại (μg/mL)")
        self.amg_card_ctrough.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.amg_card_dose_used = MetricCard(row2, "Liều đang dùng (mg)")
        self.amg_card_dose_used.grid(row=0, column=2, sticky="ew", padx=4, pady=4)
        self.amg_card_tau_used = MetricCard(row2, "τ đang dùng (h)")
        self.amg_card_tau_used.grid(row=0, column=3, sticky="ew", padx=4, pady=4)
        ttk.Separator(p, orient="horizontal").pack(fill="x", padx=6, pady=14)

        # --- E2. Đề xuất liều mới (dựa trên CLpost/Vdpost/Ke vừa tối ưu) ---
        ctk.CTkLabel(p, text="E2. Đề xuất liều mới — xem trước Cpeak/Ctrough theo tổ hợp liều-τ-Tinf",
                     font=FONT_SMALL, text_color=("gray30", "gray80")).pack(anchor="w", padx=6, pady=(4, 4))
        ctk.CTkLabel(p, text="Nhập nhiều tổ hợp (liều mới, τ mới, Tinf mới) để so sánh Cpeak/Ctrough dự đoán "
                             "(dùng CLpost/Vdpost/Ke vừa tối ưu ở Mục E) — chọn tổ hợp phù hợp nhất.",
                     font=FONT_SMALL, text_color=("gray40", "gray70"), wraplength=900, justify="left"
                     ).pack(anchor="w", padx=6, pady=(0, 6))
        self.amg_newdose_container = ctk.CTkFrame(p, fg_color="transparent")
        self.amg_newdose_container.pack(fill="x", padx=6)
        ctk.CTkButton(p, text="➕ Thêm tổ hợp liều mới", height=30, width=170,
                      command=lambda: self._add_amg_newdose_row()).pack(anchor="w", padx=6, pady=(6, 4))
        self.amg_newdose_status = StatusLabel(p)
        self.amg_newdose_status.pack(fill="x", padx=6)
        ttk.Separator(p, orient="horizontal").pack(fill="x", padx=6, pady=14)

        # --- F. Biểu đồ ---
        ctk.CTkLabel(p, text="F. Đồ thị đường cong nồng độ mô phỏng", font=FONT_SMALL,
                     text_color=("gray30", "gray80")).pack(anchor="w", padx=6, pady=(4, 4))
        self.amg_chart_container = ctk.CTkFrame(p, fg_color=("gray95", "gray14"), corner_radius=10)
        self.amg_chart_container.pack(fill="both", padx=6, pady=(6, 6))
        self.amg_chart_placeholder = ctk.CTkLabel(
            self.amg_chart_container, text="Biểu đồ sẽ xuất hiện sau khi chạy tối ưu Bayesian.",
            font=FONT_SMALL, text_color=("gray40", "gray70"))
        self.amg_chart_placeholder.pack(padx=20, pady=60)
        ttk.Separator(p, orient="horizontal").pack(fill="x", padx=6, pady=14)

        # --- G. Lưu / tải kết quả ---
        ctk.CTkLabel(p, text="G. Lưu / tải kết quả TDM Bayesian", font=FONT_SMALL, text_color=("gray30", "gray80")
                     ).pack(anchor="w", padx=6, pady=(4, 6))
        load_row = ctk.CTkFrame(p, fg_color="transparent")
        load_row.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkButton(load_row, text="🔍 Tải dữ liệu Bayesian (theo MSYT ở Mục 1)", height=34,
                      fg_color="#0969da", hover_color="#0550ae",
                      command=self.load_amg_bayesian).pack(fill="x")
        self.amg_load_status = StatusLabel(p)
        self.amg_load_status.pack(fill="x", padx=6, pady=(4, 6))

        self.amg_prev_tree = ttk.Treeview(p, show="headings", height=4)
        cols = ["Ngày TDM", "CL_post", "Vd_post", "Cpeak", "Ctrough", "Liều/τ"]
        self.amg_prev_tree["columns"] = cols
        for col in cols:
            self.amg_prev_tree.heading(col, text=col)
            self.amg_prev_tree.column(col, width=110, anchor="center")
        self.amg_prev_tree.pack(fill="x", padx=6, pady=(0, 10))

        ctk.CTkButton(p, text="💾 Lưu kết quả TDM Bayesian lên Cloud", height=36,
                      fg_color="#2f6f4f", hover_color="#254f39",
                      command=self.save_amg_bayesian).pack(fill="x", padx=6, pady=(0, 4))
        self.amg_save_status = StatusLabel(p)
        self.amg_save_status.pack(fill="x", padx=6, pady=(0, 20))

    # --- Quản lý dòng SCr ---
    def _add_amg_scr_row(self, scr_default=80.0, unit_default="μmol/L", dt_default=None):
        row = AmgScrRow(self.amg_scr_container, on_remove=self._remove_amg_scr_row,
                         scr_default=scr_default, unit_default=unit_default, dt_default=dt_default)
        row.pack(fill="x", pady=3)
        self.amg_scr_rows.append(row)

    def _remove_amg_scr_row(self, row):
        if row in self.amg_scr_rows:
            self.amg_scr_rows.remove(row)
        row.destroy()

    def _get_amg_scr_entries(self):
        entries = [r.get_scr() for r in self.amg_scr_rows]
        entries.sort(key=lambda e: e[1])
        return entries

    def _get_amg_representative_scr(self):
        entries = self._get_amg_scr_entries()
        return entries[-1][0] if entries else 80.0

    # --- Quản lý dòng liều ---
    def _renumber_amg_doses(self):
        for i, row in enumerate(self.amg_dose_rows):
            row.set_seq(i + 1)

    def _add_amg_dose_row(self, dose_default=400.0, tau_default=24.0, dt_default=None):
        if dt_default is None:
            if self.amg_dose_rows:
                last_r = self.amg_dose_rows[-1]
                dt_default = last_r.get_dose().given_at + datetime.timedelta(hours=last_r.get_tau())
            else:
                dt_default = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        row = AmgDoseRow(self.amg_doses_container, on_remove=self._remove_amg_dose_row,
                          on_auto_add=self._auto_add_amg_dose_row,
                          dose_default=dose_default, tau_default=tau_default, dt_default=dt_default)
        row.pack(fill="x", pady=3)
        self.amg_dose_rows.append(row)
        self._renumber_amg_doses()

    def _insert_amg_dose_row(self, dose_default, tau_default, dt_default, index):
        row = AmgDoseRow(self.amg_doses_container, on_remove=self._remove_amg_dose_row,
                          on_auto_add=self._auto_add_amg_dose_row,
                          dose_default=dose_default, tau_default=tau_default, dt_default=dt_default)
        row.pack(fill="x", pady=3)
        self.amg_dose_rows.insert(index, row)
        self._renumber_amg_doses()

    def _auto_add_amg_dose_row(self, current_row):
        try:
            idx = self.amg_dose_rows.index(current_row)
            cur_dose = current_row.get_dose()
            cur_tau = current_row.get_tau()
            self._insert_amg_dose_row(cur_dose.dose_mg, cur_tau,
                                       cur_dose.given_at + datetime.timedelta(hours=cur_tau), idx + 1)
        except Exception:
            self._add_amg_dose_row()

    def _remove_amg_dose_row(self, row):
        if row in self.amg_dose_rows:
            self.amg_dose_rows.remove(row)
        row.destroy()
        self._renumber_amg_doses()

    def _get_amg_doses(self):
        doses = [r.get_dose() for r in self.amg_dose_rows]
        doses.sort(key=lambda d: d.given_at)
        return doses

    def _find_amg_dose_row_for(self, dose):
        if dose is None:
            return None
        for r in self.amg_dose_rows:
            if r.get_dose().given_at == dose.given_at:
                return r
        return None

    # --- Quản lý dòng điểm đo ---
    def _add_amg_meas_row(self, cobs_default=8.0, tinf_default=1.0, dt_default=None):
        row = AmgMeasRow(self.amg_meas_container, on_remove=self._remove_amg_meas_row,
                          cobs_default=cobs_default, tinf_default=tinf_default, dt_default=dt_default)
        row.pack(fill="x", pady=3)
        self.amg_meas_rows.append(row)

    def _remove_amg_meas_row(self, row):
        if row in self.amg_meas_rows:
            self.amg_meas_rows.remove(row)
        row.destroy()

    def _get_amg_measurements(self):
        measurements = [r.get_measurement() for r in self.amg_meas_rows]
        measurements.sort(key=lambda m: m.t_obs)
        return measurements

    # --- Chạy tối ưu Bayesian (nhiều điểm đo, gom theo khoảng đưa liều, giải tuần tự) ---
    def run_amg_bayes_solve(self):
        doses = self._get_amg_doses()
        if not doses:
            self.amg_solve_status.show("⚠️ Vui lòng nhập ít nhất 1 liều ở Mục C.", "warning")
            return
        measurements = self._get_amg_measurements()
        if not measurements or any(m.c_obs <= 0 for m in measurements):
            self.amg_solve_status.show("⚠️ Vui lòng nhập ít nhất 1 điểm đo hợp lệ (Cobs > 0) ở Mục D.", "warning")
            return
        scr_entries = self._get_amg_scr_entries()
        if not scr_entries:
            self.amg_solve_status.show("⚠️ Vui lòng nhập ít nhất 1 lần đo SCr ở Mục B.", "warning")
            return

        blocks, orphans = group_measurements_by_dose_block_amg(measurements, doses)
        if not blocks:
            self.amg_solve_status.show(
                "⚠️ Không xác định được liều 'neo' cho (các) điểm đo — Tobs phải sau liều đầu tiên.", "warning")
            return

        patient = self._get_amg_patient()
        self.amg_priors, _ = compute_population_priors_amg(patient)

        block_results = solve_bayesian_sequential_amg(
            doses, blocks, self.amg_priors,
            lambda scr: recompute_cl_prior_amg(patient, scr),
            lambda t: find_nearest_scr_amg(scr_entries, t))
        self.amg_block_results = block_results
        result = block_results[-1] if block_results else None
        self.amg_bayes_result = result
        self.amg_measurement_used = blocks[-1]["measurements"] if blocks else []
        self.amg_doses_used = doses

        if result is None or not result.success:
            msg = result.message if result else "Không có block dữ liệu hợp lệ."
            self.amg_solve_status.show(f"❌ {msg}", "error")
            return

        n_orphan = f" (bỏ qua {len(orphans)} điểm đo trước liều đầu tiên)" if orphans else ""
        n_block = f" — đã chạy tuần tự qua {len(block_results)} lần TDM" if len(block_results) > 1 else ""
        self.amg_solve_status.show(f"✅ {result.message}{n_block}{n_orphan}", "success")
        self.amg_card_cl.set_value(f"{result.CL_optimized:.4f}")
        self.amg_card_vd.set_value(f"{result.Vd_optimized:.2f}")
        self.amg_card_ke.set_value(f"{result.Ke:.4f}")
        self.amg_card_ofv.set_value(f"{result.OFV_final:.4f}")

        anchor_row = self._find_amg_dose_row_for(result.anchor_dose) or (
            max(self.amg_dose_rows, key=lambda r: r.get_dose().given_at) if self.amg_dose_rows else None)
        if anchor_row is not None:
            tau_used = anchor_row.get_tau()
            dose_used = anchor_row.get_dose().dose_mg
            tinf_used = self.amg_measurement_used[0].t_inf_h if self.amg_measurement_used else 1.0
            cpeak, ctrough = compute_css_peak_trough_amg(dose_used, tau_used, tinf_used,
                                                           result.CL_optimized, result.Vd_optimized)
            self.amg_card_cpeak.set_value(f"{cpeak:.2f}")
            self.amg_card_ctrough.set_value(f"{ctrough:.2f}")
            self.amg_card_dose_used.set_value(f"{dose_used:g}")
            self.amg_card_tau_used.set_value(f"{tau_used:g}")
            self._amg_last_dose_used, self._amg_last_tau_used = dose_used, tau_used
            self._amg_last_cpeak, self._amg_last_ctrough = cpeak, ctrough

            # Gợi ý sẵn 1 tổ hợp liều mới (bằng liều/τ đang dùng) để người dùng chỉnh tiếp — chỉ thêm
            # nếu Mục E2 đang trống, không ghi đè các tổ hợp người dùng đã tự nhập trước đó
            if not self.amg_newdose_rows:
                new_row = self._add_amg_newdose_row(dose_default=dose_used, tau_default=tau_used, tinf_default=tinf_used)
                self._compute_amg_newdose_row(new_row)

        self._refresh_amg_chart()

    def _refresh_amg_chart(self):
        r = self.amg_bayes_result
        if r is None or not r.success:
            return
        meas_list = self.amg_measurement_used or []
        t_inf = meas_list[0].t_inf_h if meas_list else 1.0
        t_end = (max(m.t_obs for m in meas_list) if meas_list else datetime.datetime.now()) + datetime.timedelta(hours=12)
        times, concs = simulate_concentration_curve_amg(r.CL_optimized, r.Vd_optimized, self.amg_doses_used,
                                                          t_inf, t_end=t_end)
        if self.amg_chart_canvas is None:
            self.amg_chart_placeholder.pack_forget()
            fig = Figure(figsize=(7.5, 4.2), dpi=100)
            self.amg_chart_ax = fig.add_subplot(111)
            self.amg_chart_canvas = FigureCanvasTkAgg(fig, master=self.amg_chart_container)
            self.amg_chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        ax = self.amg_chart_ax
        ax.clear()
        if times:
            ax.plot(times, concs, color="#8250df", linewidth=2, label="Nồng độ dự đoán C(t) hậu nghiệm")
        if meas_list:
            ax.scatter([m.t_obs for m in meas_list], [m.c_obs for m in meas_list],
                       color="#d1242f", zorder=5, label="Cobs đo được")
        ax.set_xlabel("Thời gian")
        ax.set_ylabel("Nồng độ (μg/mL)")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(alpha=0.25)
        ax.tick_params(axis="x", rotation=25, labelsize=8)
        self.amg_chart_canvas.figure.tight_layout()
        self.amg_chart_canvas.draw()

    # --- Đề xuất liều mới (E2) ---
    def _add_amg_newdose_row(self, dose_default=None, tau_default=None, tinf_default=1.0):
        dose_default = dose_default if dose_default is not None else getattr(self, "_amg_last_dose_used", 400.0)
        tau_default = tau_default if tau_default is not None else getattr(self, "_amg_last_tau_used", 24.0)
        row = AmgNewDoseRow(self.amg_newdose_container, on_remove=self._remove_amg_newdose_row,
                             on_compute=self._compute_amg_newdose_row,
                             dose_default=dose_default, tau_default=tau_default, tinf_default=tinf_default)
        row.pack(fill="x", pady=3)
        self.amg_newdose_rows.append(row)
        return row

    def _remove_amg_newdose_row(self, row):
        if row in self.amg_newdose_rows:
            self.amg_newdose_rows.remove(row)
        row.destroy()

    def _compute_amg_newdose_row(self, row):
        if self.amg_bayes_result is None or not self.amg_bayes_result.success:
            self.amg_newdose_status.show("⚠️ Vui lòng chạy tối ưu Bayesian (Mục E) trước.", "warning")
            return
        dose, tau, tinf = row.get_combo()
        if dose <= 0 or tau <= 0 or tinf <= 0:
            self.amg_newdose_status.show("⚠️ Liều/τ/Tinf phải lớn hơn 0.", "warning")
            return
        cpeak, ctrough = compute_css_peak_trough_amg(dose, tau, tinf, self.amg_bayes_result.CL_optimized,
                                                       self.amg_bayes_result.Vd_optimized)
        row.set_result(cpeak, ctrough)
        self.amg_newdose_status.show("✅ Đã tính Cpeak/Ctrough dự đoán cho tổ hợp liều mới.", "success")

    # --- Lưu / tải kết quả TDM Bayesian ---
    def save_amg_bayesian(self):
        msyt = self.msyt_entry.get().strip()
        if not msyt:
            self.amg_save_status.show("⚠️ Vui lòng nhập MSYT ở Mục 1.", "error")
            return
        if self.amg_bayes_result is None or not self.amg_bayes_result.success:
            self.amg_save_status.show("⚠️ Vui lòng chạy tối ưu Bayesian trước khi lưu.", "warning")
            return

        patient = self._get_amg_patient()
        r = self.amg_bayes_result
        m = self.amg_measurement_used[-1]
        date_str = m.t_obs.strftime("%Y-%m-%d")
        doses_payload = [{"dose_mg": d.dose_mg, "given_at": d.given_at.strftime("%Y-%m-%d %H:%M")}
                          for d in self.amg_doses_used]
        scr_payload = [{"scr": v, "unit": u, "measured_at": dt.strftime("%Y-%m-%d %H:%M")}
                       for v, u, dt in (r.get_raw() for r in self.amg_scr_rows)]
        meas_payload = [{"c_obs": mm.c_obs, "t_obs": mm.t_obs.strftime("%Y-%m-%d %H:%M"), "t_inf_h": mm.t_inf_h}
                        for mm in self._get_amg_measurements()]

        ok1, msg1 = db.save_amg_bayesian_patient_current(
            msyt=msyt, age=patient.age, gender=patient.gender, height=patient.height_cm,
            weight=patient.weight_kg, scr=patient.scr_value, doses_json=doses_payload,
            scr_json=scr_payload, measurements_json=meas_payload,
        )
        ok2, msg2 = db.save_amg_bayesian_result_history(
            msyt=msyt, tdm_date=date_str, model="Aréchiga-Alvarado 2020",
            cl_prior=self.amg_priors.cl_prior if self.amg_priors else None,
            vd_prior=self.amg_priors.vd_prior if self.amg_priors else None,
            cl_optimized=r.CL_optimized, vd_optimized=r.Vd_optimized, ke=r.Ke,
            cpeak_current=getattr(self, "_amg_last_cpeak", None),
            ctrough_current=getattr(self, "_amg_last_ctrough", None),
            dose_used=getattr(self, "_amg_last_dose_used", None),
            tau_used=getattr(self, "_amg_last_tau_used", None),
            ofv_final=r.OFV_final,
        )
        if ok1 and ok2:
            self.amg_save_status.show("✅ Đã lưu dữ liệu Bayesian + thêm mới vào lịch sử.", "success")
        else:
            combined = "; ".join(msg for ok, msg in [(ok1, msg1), (ok2, msg2)] if not ok)
            self.amg_save_status.show(f"⚠️ Lưu chưa trọn vẹn: {combined}", "error")

    def load_amg_bayesian(self):
        msyt = self.msyt_entry.get().strip()
        if not msyt:
            self.amg_load_status.show("⚠️ Vui lòng nhập MSYT ở Mục 1.", "warning")
            return
        record = db.get_amg_bayesian_patient_current(msyt)
        if not record:
            self.amg_load_status.show("❌ Không tìm thấy dữ liệu Bayesian nào cho MSYT này.", "error")
            self.amg_prev_tree.delete(*self.amg_prev_tree.get_children())
            return

        for row in list(self.amg_newdose_rows):
            self._remove_amg_newdose_row(row)
        self.amg_bayes_result = None

        if record.get("age") is not None:
            self.age_entry.set(record.get("age"))
        if record.get("height") is not None:
            self.height_entry.set(record.get("height"))
        if record.get("weight") is not None:
            self.weight_entry.set(record.get("weight"))
        gender_raw = str(record.get("gender") or "nam").strip().lower()
        self.gender_opt.set("nam" if gender_raw in ("nam", "male", "m", "1") else "nữ")

        for row in list(self.amg_dose_rows):
            self._remove_amg_dose_row(row)
        doses_raw = record.get("doses_json") or []
        if isinstance(doses_raw, str):
            try:
                doses_raw = json.loads(doses_raw)
            except Exception:
                doses_raw = []
        parsed = sorted([(parse_float(it.get("dose_mg"), 0.0), parse_amg_dt(it.get("given_at")))
                          for it in doses_raw], key=lambda x: x[1])
        if parsed:
            for i, (dose_mg, given_at) in enumerate(parsed):
                tau = (parsed[i + 1][1] - given_at).total_seconds() / 3600.0 if i + 1 < len(parsed) else 24.0
                self._add_amg_dose_row(dose_default=dose_mg, tau_default=(tau if tau > 0 else 24.0), dt_default=given_at)
        else:
            self._add_amg_dose_row()

        for row in list(self.amg_scr_rows):
            self._remove_amg_scr_row(row)
        scr_raw = record.get("scr_json") or []
        if isinstance(scr_raw, str):
            try:
                scr_raw = json.loads(scr_raw)
            except Exception:
                scr_raw = []
        if scr_raw:
            for it in scr_raw:
                # Dữ liệu cũ (lưu trước khi có ô chọn đơn vị) không có khóa "unit" -> mặc định
                # μmol/L để tương thích ngược (giữ đúng hành vi tự quy đổi trước đây).
                self._add_amg_scr_row(scr_default=parse_float(it.get("scr"), 80.0),
                                       unit_default=it.get("unit") or "μmol/L",
                                       dt_default=parse_amg_dt(it.get("measured_at")))
        elif record.get("scr") is not None:
            # Cột "scr" đại diện (dữ liệu cũ) luôn được lưu ở dạng ĐÃ quy đổi mg/dL
            self._add_amg_scr_row(scr_default=record.get("scr"), unit_default="mg/dL")
        else:
            self._add_amg_scr_row()

        for row in list(self.amg_meas_rows):
            self._remove_amg_meas_row(row)
        meas_raw = record.get("measurements_json") or []
        if isinstance(meas_raw, str):
            try:
                meas_raw = json.loads(meas_raw)
            except Exception:
                meas_raw = []
        if meas_raw:
            for it in meas_raw:
                self._add_amg_meas_row(cobs_default=parse_float(it.get("c_obs"), 8.0),
                                        tinf_default=parse_float(it.get("t_inf_h"), 1.0),
                                        dt_default=parse_amg_dt(it.get("t_obs")))
        else:
            self._add_amg_meas_row()

        history = db.get_amg_bayesian_results_history(msyt)
        self.amg_prev_tree.delete(*self.amg_prev_tree.get_children())
        for row in history:
            d_date = str(row.get("tdm_date", ""))
            cl = f"{row.get('cl_optimized', 0):.3f}" if row.get('cl_optimized') is not None else "--"
            vd = f"{row.get('vd_optimized', 0):.2f}" if row.get('vd_optimized') is not None else "--"
            cpeak = f"{row.get('cpeak_current', 0):.2f}" if row.get('cpeak_current') is not None else "--"
            ctrough = f"{row.get('ctrough_current', 0):.2f}" if row.get('ctrough_current') is not None else "--"
            dt = row.get('dose_used'); tu = row.get('tau_used')
            dose_tau = f"{dt:g}/{tu:g}" if dt is not None and tu is not None else "--"
            self.amg_prev_tree.insert("", "end", values=(d_date, cl, vd, cpeak, ctrough, dose_tau))

        self.amg_load_status.show(f"✅ Đã tải dữ liệu Bayesian cho MSYT {msyt}.", "success")










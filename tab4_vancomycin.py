"""

tab4_vancomycin.py — Tab "TDM Vancomycin (Bayes)": ước lượng hậu nghiệm CL/Vc/Vp bằng mô

hình 2 ngăn, lịch chọn ngày giờ, AUC hiện tại, lưu/tải lịch sử TDM trên Cloud.



Tách riêng khỏi app.py để phát triển/bảo trì độc lập với các tab khác. Toàn bộ logic tính

toán PK Bayes vẫn nằm nguyên trong vanco_calculations.py — file này CHỈ chứa UI.

"""



import json

import datetime

from tkinter import ttk, messagebox

import pandas as pd



import customtkinter as ctk



from matplotlib.figure import Figure

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg



import database as db

try:                                    # 4 mô hình chạy như Tucuxi — nếu thiếu file thì tab vẫn chạy với 2 mô hình cũ
    import tucuxi_engine as tue
    import tucuxi_batch as tub
except Exception:                       # pragma: no cover
    tue = None
    tub = None

from vanco_calculations import (

    VancoPatientInfo, VancoDose, VancoMeasurement,

    compute_population_priors,

    simulate_concentration_curve,

    VancoPatientInfoCollin, compute_population_priors_collin,

    COLLIN_SD, COLLIN_CV, COLLIN_RES_ERR_PROP, GOTI_RES_ERR_ADD, GOTI_RES_ERR_PROP,

    compute_ibw_vanco, compute_bmi_vanco, compute_adjbw_vanco,

    compute_crcl_weight_vanco, compute_scr_corrected,

    compute_crcl_vanco, compute_crcl_capped,
    group_measurements_by_dose_block, solve_bayesian_sequential, find_nearest_scr_entry,
    recompute_full_priors_goti, recompute_full_priors_collin,
    compute_cpred_two_compartment_piecewise,

)

from ui_common import (

    FONT_H2, FONT_SMALL, parse_float,

    LabeledEntry, LabeledOption, LabeledCheck, MetricCard, StatusLabel,

)





def parse_vanco_datetime(value, default=None):

    """Parse chuỗi 'YYYY-MM-DD HH:MM' thành datetime.datetime. Lỗi -> default hoặc hiện tại."""

    value = str(value).strip()

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):

        try:

            return datetime.datetime.strptime(value, fmt)

        except Exception:

            continue

    return default if default is not None else datetime.datetime.now()





class DateTimePickerWindow(ctk.CTkToplevel):

    """Hộp thoại chọn ngày giờ dạng lịch trực quan tối ưu thao tác nhập liệu."""

    def __init__(self, parent, initial_dt=None, callback=None):

        super().__init__(parent)

        self.title("Chọn ngày và giờ")

        self.geometry("340+350")

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

        ctk.CTkLabel(t_frame, text="Giờ phụt (HH:MM):", font=FONT_SMALL).pack(anchor="w")

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

            d_str = self.date_entry.get().strip()

            t_str = self.time_entry.get().strip()

            full_str = f"{d_str} {t_str}"

            parsed = parse_vanco_datetime(full_str)

            if self.callback:

                self.callback(parsed)

            self.destroy()

        except Exception as e:

            messagebox.showerror("Lỗi", f"Định dạng ngày giờ không hợp lệ: {e}")





class VancoDoseRow(ctk.CTkFrame):

    """Một dòng nhập liều: Liều (mg) + Khoảng đưa liều (h) + Thời điểm bắt đầu + Nút thêm liều tự động."""



    def __init__(self, master, on_remove, on_auto_add, dose_default=1000.0, tau_default=12.0, dt_default=None, **kwargs):

        super().__init__(master, fg_color=("gray95", "gray16"), corner_radius=6, **kwargs)

        dt_default = dt_default or datetime.datetime.now().replace(minute=0, second=0, microsecond=0)



        self.on_auto_add_callback = on_auto_add

        self.dose_var = ctk.StringVar(value=str(dose_default))

        self.tau_var = ctk.StringVar(value=str(tau_default))

        self.dt_var = ctk.StringVar(value=dt_default.strftime("%Y-%m-%d %H:%M"))



        grid = ctk.CTkFrame(self, fg_color="transparent")

        grid.pack(fill="x", padx=8, pady=6)

        

        # Nhãn Số thứ tự liều

        self.seq_label = ctk.CTkLabel(grid, text="1.", font=FONT_SMALL, width=25, anchor="e")

        self.seq_label.pack(side="left", padx=(0, 6))



        ctk.CTkLabel(grid, text="Liều (mg):", font=FONT_SMALL).pack(side="left", padx=(0, 2))

        ctk.CTkEntry(grid, textvariable=self.dose_var, width=70).pack(side="left", padx=(0, 8))



        ctk.CTkLabel(grid, text="τ (h):", font=FONT_SMALL).pack(side="left", padx=(0, 2))

        ctk.CTkEntry(grid, textvariable=self.tau_var, width=45).pack(side="left", padx=(0, 8))



        ctk.CTkLabel(grid, text="Bắt đầu:", font=FONT_SMALL).pack(side="left", padx=(0, 2))

        self.dt_entry = ctk.CTkEntry(grid, textvariable=self.dt_var, width=130)

        self.dt_entry.pack(side="left", padx=(0, 4))



        ctk.CTkButton(grid, text="📅", width=32, command=self.open_calendar).pack(side="left", padx=(0, 6))

        ctk.CTkButton(grid, text="➕ Tự động", width=75, fg_color="#1f6feb", hover_color="#1158c7",

                      command=lambda: self.on_auto_add_callback(self)).pack(side="left", padx=(0, 6))

        ctk.CTkButton(grid, text="🗑", width=32, fg_color="#d1242f", hover_color="#a01c24",

                      command=lambda: on_remove(self)).pack(side="left")



    def set_seq(self, num):

        """Cập nhật nhãn số thứ tự cho dòng."""

        self.seq_label.configure(text=f"Liều {num}:")



    def open_calendar(self):

        current_dt = parse_vanco_datetime(self.dt_var.get())

        DateTimePickerWindow(self, initial_dt=current_dt, callback=lambda dt: self.dt_var.set(dt.strftime("%Y-%m-%d %H:%M")))



    def get_dose(self):

        dose_mg = parse_float(self.dose_var.get(), 0.0)

        given_at = parse_vanco_datetime(self.dt_var.get())

        return VancoDose(dose_mg=dose_mg, given_at=given_at)



    def get_tau(self):

        return parse_float(self.tau_var.get(), 12.0)





class VancoScrRow(ctk.CTkFrame):
    """Một dòng nhập SCr: Giá trị SCr + ĐƠN VỊ (μmol/L hoặc mg/dL, người dùng tự chọn) +
    Thời điểm đo + nút xóa (hỗ trợ nhiều lần đo SCr). Không còn tự đoán đơn vị theo
    ngưỡng >10 — người dùng chọn tường minh, giống Mục B của Tab 1 (Bayesian AMG)."""

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
        current_dt = parse_vanco_datetime(self.dt_var.get())
        DateTimePickerWindow(self, initial_dt=current_dt, callback=lambda dt: self.dt_var.set(dt.strftime("%Y-%m-%d %H:%M")))

    def get_scr(self):
        """Trả về (SCr ĐÃ QUY ĐỔI mg/dL theo đơn vị người dùng chọn, thời điểm đo) — dùng
        trực tiếp cho tính toán, KHÔNG còn tự đoán đơn vị theo ngưỡng >10 nữa."""
        raw = parse_float(self.scr_var.get(), 0.0)
        scr_mgdl = raw / 88.4 if self.unit_var.get() == "μmol/L" else raw
        return scr_mgdl, parse_vanco_datetime(self.dt_var.get())

    def get_raw(self):
        """Trả về (giá trị SCr GỐC người dùng nhập, đơn vị đã chọn, thời điểm đo) — dùng khi
        lưu/tải lại để hiển thị đúng như người dùng đã nhập, không hiển thị số đã quy đổi."""
        return parse_float(self.scr_var.get(), 0.0), self.unit_var.get(), parse_vanco_datetime(self.dt_var.get())


class VancoMeasRow(ctk.CTkFrame):
    """Một dòng nhập điểm đo nồng độ: Cobs + Tobs + Tinf + nút xóa (hỗ trợ nhiều điểm đo)."""

    def __init__(self, master, on_remove, cobs_default=15.0, tinf_default=1.0, dt_default=None, **kwargs):
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
        current_dt = parse_vanco_datetime(self.dt_var.get())
        DateTimePickerWindow(self, initial_dt=current_dt, callback=lambda dt: self.dt_var.set(dt.strftime("%Y-%m-%d %H:%M")))

    def get_measurement(self):
        cobs = parse_float(self.cobs_var.get(), 0.0)
        t_obs = parse_vanco_datetime(self.dt_var.get())
        tinf = parse_float(self.tinf_var.get(), 1.0)
        return VancoMeasurement(c_obs=cobs, t_obs=t_obs, t_inf_h=tinf)


class Tab4VancoFrame(ctk.CTkScrollableFrame):

    """

    Tab TDM Vancomycin — ước lượng hậu nghiệm Bayes (CL, Vc, Vp) bằng mô hình dược động học 2 ngăn,

    tích hợp lịch chọn ngày giờ, thêm liều tự động và tính toán AUC mới.

    """



    def __init__(self, master, app):

        super().__init__(master, fg_color="transparent")

        self.app = app

        self.dose_rows = []
        self.scr_rows = []
        self.meas_rows = []
        self.priors = None

        self.prior_details = None

        self.bayes_result = None

        self.chart_canvas = None



        self._build_patient_section()

        self._build_priors_section()

        self._build_doses_section()

        self._build_measurement_section()

        self._build_solve_section()

        self._build_auc_section()

        self._build_chart_section()

        self._build_save_section()
        self._build_batch_section()



        # Khởi tạo sẵn 2 dòng liều mẫu

        now = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)

        self._add_dose_row(dose_default=1000.0, tau_default=12.0, dt_default=now)
        self._add_dose_row(dose_default=1000.0, tau_default=12.0, dt_default=now + datetime.timedelta(hours=12))
        self._add_scr_row(scr_default=80.0, dt_default=now)
        self._add_meas_row(cobs_default=15.0, tinf_default=1.0, dt_default=now + datetime.timedelta(hours=13))

        # Hiển thị ngay thông tin dân số áp dụng của phương pháp mặc định (Goti 2018)
        self.on_method_change()



    def _section_header(self, text):

        ctk.CTkLabel(self, text=text, font=FONT_H2).pack(anchor="w", padx=6, pady=(18, 6))



    def _renumber_doses(self):

        """Đánh lại số thứ tự cho tất cả các dòng liều dùng."""

        for i, row in enumerate(self.dose_rows):

            row.set_seq(i + 1)



    # ---------------------------------------------------------------

    def _build_patient_section(self):

        self._section_header("💉 TDM Vancomycin — Bayes cá thể hóa (mô hình 2 ngăn)")

        ctk.CTkLabel(

            self,

            text="Ước lượng hậu nghiệm CL, Vc, Vp bằng tối ưu hóa Bayes dựa trên tham số tiền nghiệm quần thể.",

            font=FONT_SMALL, text_color=("gray40", "gray70"), justify="left", wraplength=900,

        ).pack(anchor="w", padx=6, pady=(0, 10))

        # --- Chọn phương pháp tính Bayes: Goti 2018 (mặc định) hoặc Collin 2019 ---
        method_row = ctk.CTkFrame(self, fg_color="transparent")
        method_row.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkLabel(method_row, text="⚙️ Phương pháp tính Bayes:", font=FONT_SMALL).pack(side="left", padx=(0, 8))
        self.method_var = ctk.StringVar(value="Goti 2018")
        self.method_menu = ctk.CTkOptionMenu(
            method_row, values=self.METHOD_CHOICES, variable=self.method_var,
            width=220, command=self.on_method_change)
        self.method_menu.pack(side="left")

        # --- Thông tin dân số áp dụng của mô hình đang chọn — cập nhật trong on_method_change() ---
        self.method_population_box = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=8)
        self.method_population_box.pack(fill="x", padx=6, pady=(0, 10))
        self.method_population_label = ctk.CTkLabel(
            self.method_population_box, text="", font=FONT_SMALL, justify="left",
            text_color=("gray25", "gray80"), wraplength=900)
        self.method_population_label.pack(anchor="w", padx=12, pady=10)

        self._section_header("1. Thông tin bệnh nhân")



        lookup_row = ctk.CTkFrame(self, fg_color="transparent")

        lookup_row.pack(fill="x", padx=6, pady=(0, 8))

        ctk.CTkButton(lookup_row, text="🔍 Tải dữ liệu bệnh nhân (theo MSYT đã nhập)", height=34,

                      fg_color="#0969da", hover_color="#0550ae",

                      command=self.load_patient_vanco).pack(fill="x")

        self.v_lookup_status = StatusLabel(self)

        self.v_lookup_status.pack(fill="x", padx=6, pady=(4, 0))



        # Hiển thị tất cả lịch sử TDM bằng bảng Treeview

        prev_row = ctk.CTkFrame(self, fg_color="transparent")

        prev_row.pack(fill="x", padx=6, pady=(6, 4))

        

        ctk.CTkLabel(prev_row, text="📋 Lịch sử kết quả TDM (Tất cả các lần):", font=FONT_SMALL,

                     text_color=("gray30", "gray80")).pack(anchor="w", pady=(0, 4))



        tree_frame = ctk.CTkFrame(prev_row, fg_color="transparent")

        tree_frame.pack(fill="x", expand=True)



        self.prev_tree = ttk.Treeview(tree_frame, show="headings", height=4)
        cols = ["Chọn", "Ngày TDM", "Phương pháp", "Cl_optimized", "Vc_optimized", "Vp_optimized", "AUC hiện tại"]
        self.prev_tree["columns"] = cols
        for col in cols:
            self.prev_tree.heading(col, text=col)
            self.prev_tree.column(col, width=(50 if col == "Chọn" else 130), anchor="center")

        # Lưu thông tin (msyt, tdm_date) của từng dòng để phục vụ xóa theo lựa chọn
        self._vanco_row_meta = {}
        self._vanco_loaded_msyt = None
        self.prev_tree.bind("<Button-1>", self._on_prev_tree_click)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.prev_tree.yview)
        self.prev_tree.configure(yscrollcommand=vsb.set)
        self.prev_tree.pack(side="left", fill="x", expand=True)
        vsb.pack(side="right", fill="y")

        del_hist_row = ctk.CTkFrame(prev_row, fg_color="transparent")
        del_hist_row.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(del_hist_row, text="🗑️ Xóa các dòng đã chọn", fg_color="#d1242f",
                      hover_color="#a01c24", width=220,
                      command=self.delete_selected_vanco_rows).pack(side="left")
        ctk.CTkLabel(del_hist_row, text="(Tick vào cột \"Chọn\" của (các) dòng cần xóa trước)",
                     font=FONT_SMALL, text_color=("gray45", "gray65")).pack(side="left", padx=(10, 0))
        self.vanco_delete_status = StatusLabel(prev_row)
        self.vanco_delete_status.pack(fill="x", pady=(4, 0))



        grid = ctk.CTkFrame(self, fg_color="transparent")

        grid.pack(fill="x", padx=6, pady=(12, 0))

        for i in range(3):

            grid.grid_columnconfigure(i, weight=1, uniform="vcol")



        c1 = ctk.CTkFrame(grid, fg_color="transparent")

        c1.grid(row=0, column=0, sticky="new", padx=(0, 10))

        self.v_msyt_entry = LabeledEntry(c1, "MSYT (Bắt buộc để lưu / tải dữ liệu)")

        self.v_msyt_entry.pack(fill="x")

        self.v_gender_opt = LabeledOption(c1, "Giới tính", ["nam", "nữ"], default="nam")

        self.v_gender_opt.pack(fill="x")

        self.v_age_entry = LabeledEntry(c1, "Tuổi", default=50.0)

        self.v_age_entry.pack(fill="x")



        c2 = ctk.CTkFrame(grid, fg_color="transparent")

        c2.grid(row=0, column=1, sticky="new", padx=10)

        self.v_height_entry = LabeledEntry(c2, "Chiều cao (cm)", default=165.0)

        self.v_height_entry.pack(fill="x")

        self.v_weight_entry = LabeledEntry(c2, "Cân nặng (kg)", default=60.0)

        self.v_weight_entry.pack(fill="x")

        ctk.CTkLabel(c2, text="SCr (μmol/L hoặc mg/dL): xem Mục 1b bên dưới (hỗ trợ nhiều lần đo)",
                     font=FONT_SMALL, text_color=("gray45", "gray65"), wraplength=250,
                     justify="left").pack(fill="x", pady=(6, 0))



        c3 = ctk.CTkFrame(grid, fg_color="transparent")

        c3.grid(row=0, column=2, sticky="new", padx=(10, 0))

        self.v_dialysis_check = LabeledCheck(c3, "Đang lọc máu (Hemodialysis)", default=False)
        self.v_dialysis_check.pack(fill="x", pady=(10, 4))

        # --- Các trường riêng cho Collin 2019 — được tạo sẵn nhưng ẨN mặc định,
        #     chỉ hiện khi người dùng chọn phương pháp "Collin 2019" (xem on_method_change) ---
        self.v_malignancy_check = LabeledCheck(c3, "Bệnh máu ác tính (STDY10)", default=False)
        self.v_gpos_check = LabeledCheck(c3, "Nhiễm khuẩn Gram dương (dis_gpos — Yamamoto)", default=True)
        self.v_heelprick_check = LabeledCheck(c3, "Mẫu lấy gót chân - Heel-prick (STDY13)", default=False)

        ctk.CTkLabel(self, text="1b. Các lần đo SCr (Creatinin huyết thanh)", font=FONT_SMALL,
                     text_color=("gray30", "gray80")).pack(anchor="w", padx=6, pady=(14, 4))
        ctk.CTkLabel(self, text="Chọn đúng đơn vị SCr cho từng dòng — phần mềm quy đổi tự động sang mg/dL để tính toán.",
                     font=FONT_SMALL, text_color=("gray45", "gray65")).pack(anchor="w", padx=6, pady=(0, 4))
        self.scr_container = ctk.CTkFrame(self, fg_color="transparent")
        self.scr_container.pack(fill="x", padx=6)
        ctk.CTkButton(self, text="➕ Thêm lần đo SCr", height=30, width=150,
                      command=lambda: self._add_scr_row()).pack(anchor="w", padx=6, pady=(6, 4))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)



    # ---------------------------------------------------------------

    def _build_priors_section(self):

        self._section_header("2. Tham số tiền nghiệm (Priors cố định quần thể)")

        ctk.CTkLabel(

            self, text="Các thông số Q, Omega, Sai số chuẩn SD và CV được cố định theo chuẩn mô hình quần thể để tránh sai lệch.",

            font=FONT_SMALL, text_color=("gray40", "gray70"), justify="left"

        ).pack(anchor="w", padx=6, pady=(0, 6))



        priors_info_frame = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=8)

        priors_info_frame.pack(fill="x", padx=6, pady=(4, 8))

        

        info_text = "• Q = 6.5 L/h (Cố định)\n• ωCL = 0.398  |  ωVc = 0.816  |  ωVp = 0.571\n• SD sai số dư = 3.4  |  CV sai số dư = 0.227 (22.7%)"
        self.priors_info_label = ctk.CTkLabel(priors_info_frame, text=info_text, font=FONT_SMALL, justify="left", text_color=("gray25", "gray80"))
        self.priors_info_label.pack(anchor="w", padx=12, pady=10)
        # Lưu sẵn text gốc của Goti để khôi phục khi chuyển phương pháp qua lại
        self._goti_priors_info_text = info_text



        ctk.CTkButton(self, text="🔄 Cập nhật/Tính toán tham số tiền nghiệm", height=34,

                      command=self.calc_priors).pack(fill="x", padx=6, pady=(0, 8))



        row = ctk.CTkFrame(self, fg_color="transparent")

        row.pack(fill="x", padx=6)

        row.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="pr")

        self.card_crcl = MetricCard(row, "CrCl (mL/phút, đã cap 150)")

        self.card_crcl.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        self.card_cl_prior = MetricCard(row, "CLprior (L/h)")

        self.card_cl_prior.grid(row=0, column=1, sticky="ew", padx=4, pady=4)

        self.card_vc_prior = MetricCard(row, "Vc,prior (L)")

        self.card_vc_prior.grid(row=0, column=2, sticky="ew", padx=4, pady=4)

        self.card_vp_prior = MetricCard(row, "Vp,prior (L)")

        self.card_vp_prior.grid(row=0, column=3, sticky="ew", padx=4, pady=4)



        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)



    def _get_patient(self):

        return VancoPatientInfo(

            age=self.v_age_entry.get_float(50.0),

            gender=self.v_gender_opt.get(),

            height_cm=self.v_height_entry.get_float(165.0),

            weight_kg=self.v_weight_entry.get_float(60.0),

            scr_value=self._get_representative_scr(),

            is_dialysis=self.v_dialysis_check.get(),

        )

    def _get_patient_collin(self):
        """Giống _get_patient() nhưng dùng cho phương pháp Collin 2019 — thay is_dialysis
        bằng 2 hiệp biến riêng: bệnh máu ác tính (STDY10) và mẫu lấy gót chân (STDY13)."""
        return VancoPatientInfoCollin(
            age=self.v_age_entry.get_float(50.0),
            gender=self.v_gender_opt.get(),
            height_cm=self.v_height_entry.get_float(165.0),
            weight_kg=self.v_weight_entry.get_float(60.0),
            scr_value=self._get_representative_scr(),
            is_malignancy=self.v_malignancy_check.get(),
            is_heelprick=self.v_heelprick_check.get(),
        )

    # Thông tin dân số áp dụng / thận trọng của từng mô hình — hiển thị ngay cạnh ô chọn mô hình.
    POPULATION_INFO = {
        "Goti 2018": (
            "👥 Dân số áp dụng: người lớn (>16 tuổi) nằm viện/ICU — có hệ số hiệu chỉnh riêng "
            "cho bệnh nhân lọc máu ngắt quãng (HD).\n"
            "⚠️ Thận trọng (cả 2 mô hình): bệnh nhân lọc máu liên tục (CRRT), ECMO, hoặc biến động "
            "sinh lý quá nhanh (sốc nhiễm khuẩn, đa chấn thương) — nên ưu tiên đo TDM 2 mẫu máu."
        ),
        "Collin 2019": (
            "👥 Dân số áp dụng: mọi lứa tuổi (từ trẻ sơ sinh đến người rất cao tuổi), kể cả thể "
            "trạng cực đoan (béo phì, teo cơ/SCr rất thấp) hoặc ung thư máu.\n"
            "⚠️ Thận trọng (cả 2 mô hình): bệnh nhân lọc máu liên tục (CRRT), ECMO, hoặc biến động "
            "sinh lý quá nhanh (sốc nhiễm khuẩn, đa chấn thương) — nên ưu tiên đo TDM 2 mẫu máu."
        ),
    }

    METHOD_CHOICES = ["Goti 2018", "Collin 2019"] + (list(tue.MODEL_FILES) if tue else [])

    _TUCUXI_NOTE = (
        "\nℹ️ Chạy NHƯ TUCUXI từ file .tdd gốc: một bộ η cho toàn bộ lịch sử, CL đổi theo ngày theo SCr "
        "(nội suy tuyến tính), CrCl = Cockcroft–Gault, không sàn SCr/không cap. Khác 2 phương pháp trên "
        "(giải tuần tự từng lần TDM, tiền nghiệm tính lại mỗi lần)."
    )
    POPULATION_INFO["tucuxi.goti"] = (
        "👥 Mô hình Goti 2018 theo file Tucuxi: người lớn (>16 tuổi) nằm viện/ICU, có hệ số lọc máu ngắt quãng (HD). "
        "CL = 4,5·(CrCl/120)^0,8 với CrCl Cockcroft–Gault do Tucuxi tính từ SCr, không sàn SCr và không giới hạn trên; "
        "V2 cố định 38,4 L." + _TUCUXI_NOTE
    )
    POPULATION_INFO["tucuxi.collin"] = (
        "👥 Mô hình Collin 2019 theo file Tucuxi: mọi lứa tuổi (sơ sinh → rất cao tuổi), thể trạng cực đoan, ung thư máu "
        "(ô 'Bệnh máu ác tính' = dis_haem). Không có hiệp biến lấy gót chân. Lưu ý: file .tdd lưu phương sai trong "
        "thẻ stdDev nên biến thiên cá thể hiệu dụng rất chặt — mô hình ít 'học' từ nồng độ đo." + _TUCUXI_NOTE
    )
    POPULATION_INFO["tucuxi.thomson"] = (
        "👥 Mô hình Thomson 2009 theo file Tucuxi: người lớn điều trị vancomycin thường quy (398 bệnh nhân xây dựng mô hình). "
        "CL phụ thuộc CrCl Cockcroft–Gault (cân nặng thực), V1 = 0,675 L/kg, V2 = 0,732 L/kg. File .tdd ghi chú việc dùng "
        "CLcr còn cần xác nhận." + _TUCUXI_NOTE
    )
    POPULATION_INFO["tucuxi.yamamoto"] = (
        "👥 Mô hình Yamamoto 2009 theo file Tucuxi: người lớn nhiễm khuẩn Gram dương (đặc biệt viêm phổi), CL tuyến tính theo "
        "CrCl khi < 85 mL/phút và hằng số khi ≥ 85. Ô 'Nhiễm Gram dương' đổi V1/V2. File .tdd không tự tính CrCl: phần "
        "mềm cấp CrCl Cockcroft–Gault từ SCr (như Goti/Thomson). Sai số dư tỉ lệ 14,3%." + _TUCUXI_NOTE
    )

    def on_method_change(self, choice=None):
        """Chuyển đổi hiển thị giữa các phương pháp: Goti 2018 (mặc định), Collin 2019 và 4 mô hình tucuxi.*."""
        method = self.method_var.get()
        self.method_population_label.configure(text=self.POPULATION_INFO.get(method, ""))
        for w in (self.v_dialysis_check, self.v_malignancy_check, self.v_heelprick_check, self.v_gpos_check):
            w.pack_forget()
        if method == "Collin 2019":
            self.v_malignancy_check.pack(fill="x", pady=(10, 4))
            self.v_heelprick_check.pack(fill="x", pady=(4, 4))
        elif method == "tucuxi.collin":
            self.v_malignancy_check.pack(fill="x", pady=(10, 4))
        elif method == "tucuxi.yamamoto":
            self.v_gpos_check.pack(fill="x", pady=(10, 4))
        elif method == "tucuxi.thomson":
            pass
        else:                                   # Goti 2018 và tucuxi.goti
            self.v_dialysis_check.pack(fill="x", pady=(10, 4))
        # Tính lại ngay các thẻ tiền nghiệm (Mục 2) theo phương pháp vừa chọn
        self.calc_priors()

    def load_patient_vanco(self):

        """

        Tải lại thông tin bệnh nhân + chế độ liều dùng đã nhập ở lần TDM Vancomycin GẦN NHẤT

        (bảng vanco_patient_current — chỉ lưu 1 bản mới nhất / MSYT) và hiển thị TẤT CẢ LỊCH SỬ

        (bảng vanco_results_history) theo MSYT đang nhập ở Mục 1.

        """

        msyt = self.v_msyt_entry.get().strip()

        if not msyt:

            self.v_lookup_status.show("⚠️ Vui lòng nhập MSYT trước khi tải dữ liệu.", "warning")

            return



        record = db.get_vanco_patient_current(msyt)

        if not record:

            self.v_lookup_status.show(
                "❌ Không tìm thấy dữ liệu TDM Vancomycin nào cho MSYT này trên Cloud.", "error")
            self.prev_tree.delete(*self.prev_tree.get_children())
            self._vanco_row_meta = {}
            self._vanco_loaded_msyt = None
            return



        # --- 1) Thông tin bệnh nhân (bắt buộc) ---

        gender_raw = str(record.get("gender") or "nam").strip().lower()

        gender_display = "nam" if gender_raw in ("nam", "male", "m", "1") else "nữ"

        self.v_gender_opt.set(gender_display)

        if record.get("age") is not None:

            self.v_age_entry.set(record.get("age"))

        if record.get("height") is not None:

            self.v_height_entry.set(record.get("height"))

        if record.get("weight") is not None:

            self.v_weight_entry.set(record.get("weight"))

        self.v_dialysis_check.set(bool(record.get("is_dialysis")))
        self.method_var.set(record.get("method") or "Goti 2018")
        self.v_malignancy_check.set(bool(record.get("is_malignancy")))
        self.v_heelprick_check.set(bool(record.get("is_heelprick")))
        # tucuxi.yamamoto: cờ "nhiễm Gram dương" được lưu ở cột is_heelprick (cột này không dùng cho mô hình đó)
        self.v_gpos_check.set(bool(record.get("is_heelprick")) if record.get("method") == "tucuxi.yamamoto" else True)
        self.on_method_change()

        # --- 1b) Các lần đo SCr đã nhập ở lần trước (scr_json); nếu chưa có thì dùng "scr" đơn cũ ---
        scr_raw = record.get("scr_json") or []
        if isinstance(scr_raw, str):
            try:
                scr_raw = json.loads(scr_raw)
            except Exception:
                scr_raw = []
        for row in list(self.scr_rows):
            self._remove_scr_row(row)
        if scr_raw:
            for item in scr_raw:
                # Dữ liệu cũ (lưu trước khi có ô chọn đơn vị) không có khóa "unit" -> mặc định
                # μmol/L để tương thích ngược (giữ đúng hành vi tự quy đổi trước đây).
                self._add_scr_row(scr_default=parse_float(item.get("scr"), 80.0),
                                   unit_default=item.get("unit") or "μmol/L",
                                   dt_default=parse_vanco_datetime(item.get("measured_at")))
        elif record.get("scr") is not None:
            # Cột "scr" đại diện (dữ liệu cũ) luôn được lưu ở dạng ĐÃ quy đổi mg/dL
            self._add_scr_row(scr_default=record.get("scr"), unit_default="mg/dL")
        else:
            self._add_scr_row()



        # --- 2) Chế độ liều dùng đã nhập ở lần TDM trước (bắt buộc) ---

        doses_raw = record.get("doses_json") or []

        if isinstance(doses_raw, str):

            try:

                doses_raw = json.loads(doses_raw)

            except Exception:

                doses_raw = []



        for row in list(self.dose_rows):

            self._remove_dose_row(row)



        parsed_doses = []

        for item in doses_raw:

            dose_mg = parse_float(item.get("dose_mg"), 0.0)

            given_at = parse_vanco_datetime(item.get("given_at"))

            parsed_doses.append((dose_mg, given_at))

        parsed_doses.sort(key=lambda x: x[1])



        if parsed_doses:

            for i, (dose_mg, given_at) in enumerate(parsed_doses):

                if i + 1 < len(parsed_doses):

                    tau = (parsed_doses[i + 1][1] - given_at).total_seconds() / 3600.0

                    if tau <= 0:

                        tau = 12.0

                else:

                    tau = 12.0

                self._add_dose_row(dose_default=dose_mg, tau_default=tau, dt_default=given_at)

        else:

            now = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)

            self._add_dose_row(dose_default=1000.0, tau_default=12.0, dt_default=now)

            

        self._renumber_doses()



        # --- 3) Kết quả TDM các lần trước (Hiển thị tất cả lịch sử) ---

        df_history = db.get_vanco_results_history(msyt)
        self.prev_tree.delete(*self.prev_tree.get_children())
        self._vanco_row_meta = {}
        self._vanco_loaded_msyt = msyt
        if not df_history.empty:
            for _, r in df_history.iterrows():
                d_date = str(r.get("tdm_date", ""))
                d_method = str(r.get("method") or "Goti 2018")
                cl = f"{r.get('cl_optimized', 0):.4f}" if pd.notnull(r.get('cl_optimized')) else "--"
                vc = f"{r.get('vc_optimized', 0):.2f}" if pd.notnull(r.get('vc_optimized')) else "--"
                vp = f"{r.get('vp_optimized', 0):.2f}" if pd.notnull(r.get('vp_optimized')) else "--"
                auc = f"{r.get('auc_current', 0):.2f}" if pd.notnull(r.get('auc_current')) else "--"
                iid = self.prev_tree.insert("", "end", values=("☐", d_date, d_method, cl, vc, vp, auc))
                # Lưu kèm "method" để xóa đúng 1 dòng khi 1 ngày có cả kết quả Goti lẫn Collin
                # (trước đây chỉ lưu msyt+ngày nên tick xóa 1 dòng sẽ xóa nhầm cả 2).
                self._vanco_row_meta[iid] = {"msyt": msyt, "tdm_date": d_date, "method": r.get("method")}



            pass  # (điểm đo được khôi phục từ measurements_json bên dưới, không phụ thuộc lịch sử)



        # --- 4) Các điểm đo Cobs/Tobs/Tinf đã nhập ở lần trước (measurements_json) ---
        meas_raw = record.get("measurements_json") or []
        if isinstance(meas_raw, str):
            try:
                meas_raw = json.loads(meas_raw)
            except Exception:
                meas_raw = []
        for row in list(self.meas_rows):
            self._remove_meas_row(row)
        if meas_raw:
            for item in meas_raw:
                self._add_meas_row(cobs_default=parse_float(item.get("c_obs"), 15.0),
                                    tinf_default=parse_float(item.get("t_inf_h"), 1.0),
                                    dt_default=parse_vanco_datetime(item.get("t_obs")))
        else:
            self._add_meas_row()

        # Tính lại priors ngay theo dữ liệu vừa tải để các thẻ Mục 2 cập nhật theo
        self.calc_priors()



        self.v_lookup_status.show(f"✅ Đã tải dữ liệu bệnh nhân {msyt}.", "success")



    # ===================================================================================
    # 4 mô hình chạy như Tucuxi (tucuxi.goti / .collin / .thomson / .yamamoto)
    # ===================================================================================
    def _tucuxi_patient(self, method):
        return tue.TuPatient(
            age_years=self.v_age_entry.get_float(50.0),
            male=(self.v_gender_opt.get() == "nam"),
            weight_kg=self.v_weight_entry.get_float(60.0),
            hemodialysis=bool(self.v_dialysis_check.get()) if method == "tucuxi.goti" else False,
            haem_malignancy=bool(self.v_malignancy_check.get()) if method == "tucuxi.collin" else False,
            gram_positive=bool(self.v_gpos_check.get()) if method == "tucuxi.yamamoto" else True,
        )

    def _tucuxi_scr_umol(self):
        """SCr nhập ở Mục 1b (đã quy về mg/dL) -> μmol/L cho engine."""
        return [(dt, v * 88.4) for v, dt in self._get_scr_entries()]

    def _tucuxi_doses(self, doses, measurements):
        """Danh sách (thời điểm, mg, thời gian truyền h). Thời gian truyền lấy từ điểm đo có liều neo là liều đó;
        liều chưa có điểm đo dùng giá trị của lần đo kế sau (hoặc lần đo cuối)."""
        doses = sorted(doses, key=lambda d: d.given_at)
        anchors = {}
        for mm in measurements:
            prior = [d for d in doses if d.given_at <= mm.t_obs]
            if prior:
                anchors[max(prior, key=lambda d: d.given_at).given_at] = mm.t_inf_h
        keys = sorted(anchors)
        default = measurements[0].t_inf_h if measurements else 1.0
        out = []
        for d in doses:
            nxt = [k for k in keys if k >= d.given_at]
            tinf = anchors[nxt[0]] if nxt else (anchors[keys[-1]] if keys else default)
            out.append((d.given_at, d.dose_mg, tinf))
        return out

    def _calc_priors_tucuxi(self, method):
        import types
        if tue is None:
            self.priors, self.prior_details = None, None
            return
        pat = self._tucuxi_patient(method)
        scr = self._tucuxi_scr_umol() or [(datetime.datetime.now(), 80.0)]
        doses = self._get_doses()
        t_ref = max([e[0] for e in scr] + [d.given_at for d in doses])
        ps, cov, model = tue.population_params(method, pat, scr, t_ref)
        sd = {p.id: p.sd for p in model.eta_params}
        self.priors = types.SimpleNamespace(
            q_prior=ps["Q"], cl_prior=ps["CL"], vc_prior=ps["V1"], vp_prior=ps["V2"],
            omega_cl=sd.get("CL", 0.0), omega_vc=sd.get("V1", 0.0), omega_vp=sd.get("V2", 0.0))
        self.prior_details = {"covariates": cov}
        uses_clcr = any("clcr" in p.inputs for p in model.params)
        self.card_crcl.set_value(f"{cov['clcr']:.1f} (Cockcroft–Gault, Tucuxi)" if uses_clcr and "clcr" in cov
                                 else "— (mô hình không dùng CrCl)")
        self.card_cl_prior.set_value(f"{ps['CL']:.3f}")
        self.card_vc_prior.set_value(f"{ps['V1']:.2f}")
        self.card_vp_prior.set_value(f"{ps['V2']:.2f}")
        omegas = "  |  ".join(f"ω{k} = {v:g}" for k, v in sd.items())
        sig = model.sigmas
        err = (f"SD = {sig[0]:g}  |  CV = {sig[1]:g}" if model.err_type == "mixed"
               else f"CV (tỉ lệ) = {sig[0]:g}")
        bsv_kind = ("proportional (P·(1+η))" if any(p.bsv_type == "proportional" for p in model.eta_params)
                    else "exponential (P·e^η)")
        self.priors_info_label.configure(text=(
            f"• Q = {ps['Q']:.3f} L/h" + (" (cố định)" if all(p.id != "Q" for p in model.eta_params) else " (có biến thiên cá thể)") + "\n"
            f"• BSV {bsv_kind}: {omegas}  (giá trị trong thẻ stdDev của .tdd dùng nguyên như độ lệch chuẩn)\n"
            f"• Sai số dư ({model.err_type}): {err}   •   Tiền nghiệm tính tại {t_ref:%Y-%m-%d %H:%M}"
        ))

    def _run_tucuxi_solve(self, doses, measurements, scr_entries):
        method = self.method_var.get()
        if tue is None:
            self.solve_status.show("❌ Thiếu module tucuxi_engine.py — không chạy được phương pháp này.", "error")
            return
        pat = self._tucuxi_patient(method)
        d3 = self._tucuxi_doses(doses, measurements)
        scr = [(dt, v * 88.4) for v, dt in scr_entries]
        samples = [(mm.t_obs, mm.c_obs) for mm in measurements]
        try:
            fit = tue.tucuxi_fit(method, pat, d3, scr, samples)
        except Exception as exc:
            self.solve_status.show(f"❌ Lỗi tính {method}: {exc}", "error")
            return
        a = fit.anchor_dose
        if a is not None:
            fit.anchor_dose = VancoDose(dose_mg=a.dose_mg, given_at=a.t)
        self.block_results = [fit]
        self.bayes_result = fit
        self.measurement_used = measurements
        self.doses_used = doses
        etas = ", ".join(f"η{p.id} = {e:+.3f}" for e, p in zip(fit.etas, fit.model.eta_params))
        cyc = ""
        try:
            tN = max(sm[0] for sm in fit.samples) if getattr(fit, "samples", None) else None
            if tN is not None:
                pc = fit.params_at_cycle(tN)
                cyc = (f"\nCL_optimized ở trên = CL tại thời điểm mới nhất (SCr mới nhất). "
                       f"CL của chu kỳ liều chứa TDM N (cách Tucuxi báo) = {pc['CL']:.3f} L/h, "
                       f"V1 = {pc['V1']:.2f}, V2 = {pc['V2']:.2f}, Q = {pc['Q']:.2f}.")
        except Exception:
            cyc = ""
        self.solve_status.show(
            f"✅ {method}: MAP hội tụ với {len(samples)} nồng độ (1 bộ η cho toàn lịch sử) — {etas}{cyc}", "success")
        self.card_cl_post.set_value(f"{fit.CL_optimized:.4f}")
        self.card_vc_post.set_value(f"{fit.Vc_optimized:.2f}")
        self.card_vp_post.set_value(f"{fit.Vp_optimized:.2f}")
        self.card_cpred_final.set_value(f"{fit.C_pred_final:.3f}")
        self.card_ofv_final.set_value(f"{fit.OFV_final:.4f}")
        self.card_k10.set_value(f"{fit.k10:.4f}")
        self.card_k12.set_value(f"{fit.k12:.4f}")
        self.card_k21.set_value(f"{fit.k21:.4f}")
        self.card_alpha.set_value(f"{fit.alpha:.4f}")
        self.card_beta.set_value(f"{fit.beta:.4f}")
        self.calc_auc()
        self.calc_auc_current()
        self.refresh_chart()

    def _tucuxi_curve(self, r, meas_list):
        t_start = min(d.given_at for d in self.doses_used)
        t_end = max([mm.t_obs for mm in meas_list] + [d.given_at for d in self.doses_used]) + datetime.timedelta(hours=12)
        total_min = max(int((t_end - t_start).total_seconds() / 60), 60)
        step = max(10, total_min // 1500)
        times = [t_start + datetime.timedelta(minutes=step * i) for i in range(total_min // step + 1)]
        return times, r.predict(times)

    def calc_priors(self):
        method = self.method_var.get() if hasattr(self, "method_var") else "Goti 2018"
        if method.startswith("tucuxi."):
            self._calc_priors_tucuxi(method)
            return

        if method == "Collin 2019":
            # --- Phương pháp Collin 2019: tiền nghiệm tính theo hiệp biến bệnh nhân ---
            patient = self._get_patient_collin()
            self.priors, self.prior_details = compute_population_priors_collin(patient)

            # Vẫn tính CrCl kiểu Goti CHỈ để hiển thị tham khảo song song (vùng A16:B23
            # của sheet Excel "collin Bayes" không được dùng trong bất kỳ công thức tiền
            # nghiệm nào của Collin — xem ghi chú trong vanco_calculations.py)
            ibw = compute_ibw_vanco(patient.gender, patient.height_cm)
            bmi = compute_bmi_vanco(patient.weight_kg, patient.height_cm)
            adjbw = compute_adjbw_vanco(patient.weight_kg, ibw)
            weight_cg = compute_crcl_weight_vanco(patient.weight_kg, ibw, adjbw, bmi)
            scr_mgdl = patient.scr_value  # đã ở dạng mg/dL (xem ghi chú đơn vị ở VancoScrRow)
            scr_corr = compute_scr_corrected(scr_mgdl, patient.age)
            crcl = compute_crcl_vanco(patient.age, patient.gender, weight_cg, scr_corr)
            crcl_capped = compute_crcl_capped(crcl)

            self.card_crcl.set_value(f"{crcl_capped:.1f} (không dùng trong Collin)")
            self.card_cl_prior.set_value(f"{self.priors.cl_prior:.3f}")
            self.card_vc_prior.set_value(f"{self.priors.vc_prior:.2f}")
            self.card_vp_prior.set_value(f"{self.priors.vp_prior:.2f}")

            self.priors_info_label.configure(text=(
                f"• Q2,prior = {self.priors.q_prior:.3f} L/h (tính theo hiệp biến bệnh nhân — mô hình Collin 2019)\n"
                f"• ωCL = {self.priors.omega_cl:.4f}  |  ωV1 = {self.priors.omega_vc:.4f}  |  ωV2 = {self.priors.omega_vp:.4f}\n"
                f"• SD sai số dư = {COLLIN_SD:.2f}  |  CV sai số dư = {COLLIN_CV:.3f} ({COLLIN_RES_ERR_PROP:.1f}%)"
            ))
        else:
            # --- Phương pháp Goti 2018 (giữ nguyên 100% như trước) ---
            patient = self._get_patient()
            # Giá trị cố định theo yêu cầu (không cho phép người dùng tự đổi)
            q = 6.5
            omega_cl = 0.398
            omega_vc = 0.816
            omega_vp = 0.571

            self.priors, self.prior_details = compute_population_priors(
                patient, q_prior=q, omega_cl=omega_cl, omega_vc=omega_vc, omega_vp=omega_vp)

            self.card_crcl.set_value(f"{self.prior_details['crcl_capped']:.1f}")
            self.card_cl_prior.set_value(f"{self.priors.cl_prior:.3f}")
            self.card_vc_prior.set_value(f"{self.priors.vc_prior:.2f}")
            self.card_vp_prior.set_value(f"{self.priors.vp_prior:.2f}")
            self.priors_info_label.configure(text=self._goti_priors_info_text)



    # ---------------------------------------------------------------

    def _build_doses_section(self):

        self._section_header("3. Lịch sử liều dùng (Truyền TM)")

        ctk.CTkLabel(

            self, text="Nhập liệu lịch sử truyền thuốc. Nhấn '➕ Tự động' để thêm liều kế tiếp tự động.",

            font=FONT_SMALL, text_color=("gray40", "gray70"), wraplength=900, justify="left",

        ).pack(anchor="w", padx=6, pady=(0, 6))



        self.doses_container = ctk.CTkFrame(self, fg_color="transparent")

        self.doses_container.pack(fill="x", padx=6)



        ctk.CTkButton(self, text="➕ Thêm liều thủ công", height=32, width=160,

                      command=lambda: self._add_dose_row()).pack(anchor="w", padx=6, pady=(6, 4))



        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)



    def _add_dose_row(self, dose_default=1000.0, tau_default=12.0, dt_default=None):

        if dt_default is None:

            if self.dose_rows:

                last_r = self.dose_rows[-1]

                dt_default = last_r.get_dose().given_at + datetime.timedelta(hours=last_r.get_tau())

            else:

                dt_default = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)

        row = VancoDoseRow(self.doses_container, on_remove=self._remove_dose_row, on_auto_add=self._auto_add_dose_row,

                            dose_default=dose_default, tau_default=tau_default, dt_default=dt_default)

        row.pack(fill="x", pady=3)

        self.dose_rows.append(row)

        self._renumber_doses()



    def _insert_dose_row(self, dose_default, tau_default, dt_default, index):

        row = VancoDoseRow(self.doses_container, on_remove=self._remove_dose_row, on_auto_add=self._auto_add_dose_row,

                            dose_default=dose_default, tau_default=tau_default, dt_default=dt_default)

        row.pack(fill="x", pady=3)

        self.dose_rows.insert(index, row)

        self._renumber_doses()



    def _auto_add_dose_row(self, current_row):

        try:

            idx = self.dose_rows.index(current_row)

            cur_dose = current_row.get_dose()

            cur_tau = current_row.get_tau()

            next_dt = cur_dose.given_at + datetime.timedelta(hours=cur_tau)

            self._insert_dose_row(dose_default=cur_dose.dose_mg, tau_default=cur_tau, dt_default=next_dt, index=idx+1)

        except Exception:

            self._add_dose_row()



    def _remove_dose_row(self, row):

        if row in self.dose_rows:

            self.dose_rows.remove(row)

        row.destroy()

        self._renumber_doses()



    def _get_doses(self):
        doses = [r.get_dose() for r in self.dose_rows]
        doses.sort(key=lambda d: d.given_at)
        return doses

    # --- Mục 1b: Các lần đo SCr (nhiều dòng) ---
    def _add_scr_row(self, scr_default=80.0, unit_default="μmol/L", dt_default=None):
        row = VancoScrRow(self.scr_container, on_remove=self._remove_scr_row,
                           scr_default=scr_default, unit_default=unit_default, dt_default=dt_default)
        row.pack(fill="x", pady=3)
        self.scr_rows.append(row)

    def _remove_scr_row(self, row):
        if row in self.scr_rows:
            self.scr_rows.remove(row)
        row.destroy()

    def _get_scr_entries(self):
        """Trả về list (scr_value, thời_điểm_đo) đã sắp xếp theo thời gian tăng dần."""
        entries = [r.get_scr() for r in self.scr_rows]
        entries.sort(key=lambda e: e[1])
        return entries

    def _get_representative_scr(self):
        """SCr 'đại diện' hiện tại — dùng để hiển thị Mục 2 (priors nền tảng ban đầu) khi
        chưa chạy tối ưu Bayes: lấy giá trị SCr có thời điểm đo GẦN NHẤT/MỚI NHẤT."""
        entries = self._get_scr_entries()
        return entries[-1][0] if entries else 80.0



    # ---------------------------------------------------------------

    def _build_measurement_section(self):
        self._section_header("4. Nồng độ đo được (TDM) — hỗ trợ nhiều điểm đo")
        ctk.CTkLabel(
            self, text="Có thể nhập nhiều lần đo (nhiều lần TDM khác khoảng đưa liều, hoặc "
                       "peak+trough cùng khoảng đưa liều). Nhấn '➕ Thêm điểm đo' để thêm dòng.",
            font=FONT_SMALL, text_color=("gray40", "gray70"), wraplength=900, justify="left",
        ).pack(anchor="w", padx=6, pady=(0, 6))

        self.meas_container = ctk.CTkFrame(self, fg_color="transparent")
        self.meas_container.pack(fill="x", padx=6)

        ctk.CTkButton(self, text="➕ Thêm điểm đo", height=32, width=140,
                      command=lambda: self._add_meas_row()).pack(anchor="w", padx=6, pady=(6, 4))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)

    def _add_meas_row(self, cobs_default=15.0, tinf_default=1.0, dt_default=None):
        row = VancoMeasRow(self.meas_container, on_remove=self._remove_meas_row,
                            cobs_default=cobs_default, tinf_default=tinf_default, dt_default=dt_default)
        row.pack(fill="x", pady=3)
        self.meas_rows.append(row)

    def _remove_meas_row(self, row):
        if row in self.meas_rows:
            self.meas_rows.remove(row)
        row.destroy()

    def _get_measurements(self):
        """Trả về list VancoMeasurement đã sắp xếp theo Tobs tăng dần."""
        measurements = [r.get_measurement() for r in self.meas_rows]
        measurements.sort(key=lambda m: m.t_obs)
        return measurements



    # ---------------------------------------------------------------

    def _build_solve_section(self):

        self._section_header("5. Chạy tối ưu hóa Bayes")

        ctk.CTkButton(self, text="🧮 CHẠY TỐI ƯU BAYES", height=38,

                      fg_color="#8250df", hover_color="#6639ba",

                      command=self.run_bayes_solve).pack(fill="x", padx=6, pady=(0, 6))

        self.solve_status = StatusLabel(self)

        self.solve_status.pack(fill="x", padx=6)



        row = ctk.CTkFrame(self, fg_color="transparent")

        row.pack(fill="x", padx=6, pady=(8, 0))

        row.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="res")

        self.card_cl_post = MetricCard(row, "CL_optimized (L/h)")

        self.card_cl_post.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        self.card_vc_post = MetricCard(row, "Vc_optimized (L)")

        self.card_vc_post.grid(row=0, column=1, sticky="ew", padx=4, pady=4)

        self.card_vp_post = MetricCard(row, "Vp_optimized (L)")

        self.card_vp_post.grid(row=0, column=2, sticky="ew", padx=4, pady=4)

        self.card_cpred_final = MetricCard(row, "C_pred_final (μg/mL)")

        self.card_cpred_final.grid(row=0, column=3, sticky="ew", padx=4, pady=4)

        self.card_ofv_final = MetricCard(row, "OFV_final")

        self.card_ofv_final.grid(row=0, column=4, sticky="ew", padx=4, pady=4)



        row2 = ctk.CTkFrame(self, fg_color="transparent")

        row2.pack(fill="x", padx=6, pady=(4, 0))

        row2.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="res2")

        self.card_k10 = MetricCard(row2, "k10 (h⁻¹)")

        self.card_k10.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        self.card_k12 = MetricCard(row2, "k12 (h⁻¹)")

        self.card_k12.grid(row=0, column=1, sticky="ew", padx=4, pady=4)

        self.card_k21 = MetricCard(row2, "k21 (h⁻¹)")

        self.card_k21.grid(row=0, column=2, sticky="ew", padx=4, pady=4)

        self.card_alpha = MetricCard(row2, "α (h⁻¹)")

        self.card_alpha.grid(row=0, column=3, sticky="ew", padx=4, pady=4)

        self.card_beta = MetricCard(row2, "β (h⁻¹)")

        self.card_beta.grid(row=0, column=4, sticky="ew", padx=4, pady=4)



        row3 = ctk.CTkFrame(self, fg_color="transparent")

        row3.pack(fill="x", padx=6, pady=(8, 0))

        ctk.CTkLabel(

            row3, text="AUC hiện tại = Liều × 24 / (τ × Clbn) — tính theo LIỀU ĐANG DÙNG (liều kề trước các điểm đo của lần TDM cuối)",

            font=FONT_SMALL, text_color=("gray40", "gray70")

        ).pack(anchor="w", pady=(0, 4))

        self.card_auc_current = MetricCard(row3, "AUC hiện tại (mg·h/L)")

        self.card_auc_current.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(
            row3, text="AUC ngày TDM = AUC₀₋₂₄ MÔ PHỎNG theo đúng các liều đã dùng (kể cả tích lũy, CL thay đổi theo SCr/AKI), "
                       "tính trong 24 h kể từ liều kề trước các điểm đo; liều chưa nhập trong cửa sổ được giả định tiếp tục theo chế độ liều cuối.",
            font=FONT_SMALL, text_color=("gray40", "gray70"), wraplength=900, justify="left"
        ).pack(anchor="w", pady=(8, 4))
        self.card_auc_day = MetricCard(row3, "AUC ngày TDM — 24 h thực tế (mg·h/L)")
        self.card_auc_day.pack(fill="x", padx=4, pady=4)
        self.auc_day_value = None
        self.auc_day_label = ctk.CTkLabel(row3, text="", font=FONT_SMALL, text_color=("gray40", "gray70"),
                                          wraplength=900, justify="left")
        self.auc_day_label.pack(anchor="w", padx=4)



        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)



    def _find_dose_row_for(self, dose):
        """Tìm VancoDoseRow tương ứng 1 VancoDose (khớp thời điểm given_at) để lấy τ."""
        if dose is None:
            return None
        for r in self.dose_rows:
            if r.get_dose().given_at == dose.given_at:
                return r
        return None

    def calc_auc_current(self):
        """AUC cân bằng (công thức cũ) + AUC ngày TDM (mô phỏng 24 h thực tế)."""
        auc = self._calc_auc_steady()
        try:
            self.calc_auc_day()
        except Exception as exc:                      # không để lỗi phụ làm hỏng luồng chính
            self.card_auc_day.set_value("Không tính được")
            self.auc_day_value = None
            self.auc_day_label.configure(text=f"({exc})")
        return auc

    def _cl_segments_for_sim(self):
        """CL bậc thang cho mô hình cũ (Goti/Collin của app) — cùng cách dùng ở calc_cpred_prediction."""
        doses = self._get_doses()
        segs = []
        seg_start = min(d.given_at for d in doses)
        for r in getattr(self, "block_results", []):
            if not r.points:
                continue
            segs.append((seg_start, r.CL_optimized))
            seg_start = max(p["t_obs"] for p in r.points)
        if not segs:
            segs = [(seg_start, self.bayes_result.CL_optimized)]
        return segs

    def calc_auc_day(self):
        """AUC₀₋₂₄ của NGÀY thực hiện TDM: tích phân (hình thang, bước 5 phút) đường cong nồng độ mô phỏng
        bằng tham số Bayes, trong 24 h kể từ thời điểm liều neo (liều kề trước các điểm đo của lần TDM cuối).
        Khác AUC cân bằng ở chỗ phản ánh liều thực tế đã dùng + tích lũy chưa đạt steady-state + CL hiện tại."""
        self.auc_day_value = None
        if self.bayes_result is None or not self.bayes_result.success or not self.dose_rows:
            self.card_auc_day.set_value("Chưa chạy solve Bayes")
            self.auc_day_label.configure(text="")
            return None
        anchor_dose = getattr(self.bayes_result, "anchor_dose", None)
        anchor_row = self._find_dose_row_for(anchor_dose)
        if anchor_row is None:
            anchor_row = max(self.dose_rows, key=lambda r: r.get_dose().given_at)
        t0 = anchor_row.get_dose().given_at
        t1 = t0 + datetime.timedelta(hours=24)
        recorded = self._get_doses()
        last_row = max(self.dose_rows, key=lambda r: r.get_dose().given_at)
        last_d, tau_l = last_row.get_dose(), last_row.get_tau()
        meas = self.measurement_used or []
        tinf = meas[0].t_inf_h if meas else 1.0
        projected = []
        if tau_l > 0:                                  # doses chưa nhập nhưng nằm trong cửa sổ 24 h → giả định tiếp tục chế độ liều cuối
            t = last_d.given_at + datetime.timedelta(hours=tau_l)
            while t < t1 and len(projected) < 200:
                projected.append(VancoDose(dose_mg=last_d.dose_mg, given_at=t))
                t += datetime.timedelta(hours=tau_l)
        step = 5
        n = 24 * 60 // step
        times = [t0 + datetime.timedelta(minutes=step * i) for i in range(n + 1)]
        if hasattr(self.bayes_result, "predict"):
            concs = self.bayes_result.predict(
                times, extra_doses=[tue.Intake(d.given_at, d.dose_mg, tinf) for d in projected])
        else:
            q = self.priors.q_prior if self.priors is not None else 6.5
            segs = self._cl_segments_for_sim()
            full = list(recorded) + projected
            concs = [compute_cpred_two_compartment_piecewise(
                segs, self.bayes_result.Vc_optimized, self.bayes_result.Vp_optimized, q, full, tt, tinf)
                for tt in times]
        auc = sum((concs[i] + concs[i + 1]) * 0.5 * (step / 60.0) for i in range(n))
        self.auc_day_value = auc
        steady = getattr(self, "auc_current_value", None)
        txt = f"{auc:.2f} mg·h/L"
        self.card_auc_day.set_value(txt)
        in_win = sum(1 for d in recorded if t0 <= d.given_at < t1)
        info = (f"Cửa sổ: {t0.strftime('%Y-%m-%d %H:%M')} → {t1.strftime('%Y-%m-%d %H:%M')} · "
                f"{in_win} liều đã nhập + {len(projected)} liều giả định tiếp tục ({last_d.dose_mg:.0f} mg q{tau_l:g}h).")
        if steady:
            info += f" So với AUC cân bằng: {auc / steady * 100:.0f}% ({auc - steady:+.1f})."
        self.auc_day_label.configure(text=info)
        return auc

    def _calc_auc_steady(self):
        """AUC hiện tại = Liều đang dùng (liều neo — kề trước các điểm đo của LẦN TDM
        cuối cùng vừa tối ưu) × 24 / (τ của liều đó × Clbn vừa tối ưu Bayes)."""
        if self.bayes_result is None or not self.bayes_result.success:
            self.card_auc_current.set_value("Chưa chạy solve Bayes")
            self.auc_current_value = None
            return None

        anchor_dose = getattr(self.bayes_result, "anchor_dose", None)
        anchor_row = self._find_dose_row_for(anchor_dose)
        if anchor_row is None and self.dose_rows:
            anchor_row = max(self.dose_rows, key=lambda r: r.get_dose().given_at)
        if anchor_row is None:
            self.card_auc_current.set_value("Chưa có liều ở Mục 3")
            self.auc_current_value = None
            return None

        dose_mg = anchor_row.get_dose().dose_mg
        tau = anchor_row.get_tau()
        clbn = self.bayes_result.CL_optimized
        if tau <= 0 or clbn <= 0:
            self.card_auc_current.set_value("Giá trị không hợp lệ")
            self.auc_current_value = None
            return None

        auc = (dose_mg * 24.0) / (tau * clbn)
        self.card_auc_current.set_value(f"{auc:.2f} mg·h/L")
        self.auc_current_value = auc
        return auc

    def run_bayes_solve(self):
        self.calc_priors()
        doses = self._get_doses()
        if not doses:
            self.solve_status.show("⚠️ Vui lòng nhập ít nhất 1 liều ở Mục 3.", "warning")
            return

        measurements = self._get_measurements()
        if not measurements or any(m.c_obs <= 0 for m in measurements):
            self.solve_status.show("⚠️ Vui lòng nhập ít nhất 1 điểm đo hợp lệ (Cobs > 0) ở Mục 4.", "warning")
            return

        scr_entries = self._get_scr_entries()
        if not scr_entries:
            self.solve_status.show("⚠️ Vui lòng nhập ít nhất 1 lần đo SCr ở Mục 1b.", "warning")
            return

        if self.method_var.get().startswith("tucuxi."):
            self._run_tucuxi_solve(doses, measurements, scr_entries)
            return
        blocks, orphans = group_measurements_by_dose_block(measurements, doses)
        if not blocks:
            self.solve_status.show(
                "⚠️ Không xác định được liều 'neo' cho (các) điểm đo — Tobs phải sau liều đầu tiên.", "warning")
            return

        method = self.method_var.get()
        if method == "Collin 2019":
            sd, cv = COLLIN_SD, COLLIN_CV
            patient = self._get_patient_collin()
            recompute_priors_fn = lambda scr: recompute_full_priors_collin(patient, scr)
        else:
            sd, cv = GOTI_RES_ERR_ADD, GOTI_RES_ERR_PROP
            patient = self._get_patient()
            recompute_priors_fn = lambda scr: recompute_full_priors_goti(patient, scr)
        nearest_scr_entry_fn = lambda t_obs: find_nearest_scr_entry(scr_entries, t_obs)

        # SỬA (2026-09): MỌI lần TDM (kể cả lần đầu) đều dùng tiền nghiệm CL/Vc/Vp/Q tính lại
        # hoàn toàn mới từ mô hình quần thể (không còn kế thừa Vc/Vp hậu nghiệm của lần trước)
        # — tránh dữ liệu bệnh nhân trôi dạt khỏi quần thể tham khảo qua nhiều lần TDM liên tiếp.
        block_results = solve_bayesian_sequential(doses, blocks, recompute_priors_fn,
                                                    nearest_scr_entry_fn, sd=sd, cv=cv)
        self.block_results = block_results
        result = block_results[-1] if block_results else None
        self.bayes_result = result
        self.measurement_used = blocks[-1]["measurements"] if blocks else []
        self.doses_used = doses

        if result is None or not result.success:
            msg = result.message if result else "Không có block dữ liệu hợp lệ."
            self.solve_status.show(f"❌ {msg}", "error")
            return

        n_orphan_note = f" (bỏ qua {len(orphans)} điểm đo trước liều đầu tiên)" if orphans else ""
        n_block_note = f" — đã chạy tuần tự qua {len(block_results)} lần TDM (khoảng đưa liều)" if len(block_results) > 1 else ""
        self.solve_status.show(f"✅ {result.message}{n_block_note}{n_orphan_note}", "success")
        self.card_cl_post.set_value(f"{result.CL_optimized:.4f}")
        self.card_vc_post.set_value(f"{result.Vc_optimized:.2f}")
        self.card_vp_post.set_value(f"{result.Vp_optimized:.2f}")
        self.card_cpred_final.set_value(f"{result.C_pred_final:.3f}")
        self.card_ofv_final.set_value(f"{result.OFV_final:.4f}")
        self.card_k10.set_value(f"{result.k10:.4f}")
        self.card_k12.set_value(f"{result.k12:.4f}")
        self.card_k21.set_value(f"{result.k21:.4f}")
        self.card_alpha.set_value(f"{result.alpha:.4f}")
        self.card_beta.set_value(f"{result.beta:.4f}")

        # Tự động tính AUC luôn nếu đã có thông số mới
        self.calc_auc()
        self.calc_auc_current()
        self.refresh_chart()



    # ---------------------------------------------------------------

    def _build_auc_section(self):

        self._section_header("6. Tính toán AUC theo liều mới")

        ctk.CTkLabel(

            self, text="Công thức: AUC = (Liều mới x 24) / (Khoảng đưa liều x Clbn)",

            font=FONT_SMALL, text_color=("gray40", "gray70"), justify="left"

        ).pack(anchor="w", padx=6, pady=(0, 6))



        row = ctk.CTkFrame(self, fg_color="transparent")

        row.pack(fill="x", padx=6)

        row.grid_columnconfigure((0, 1), weight=1, uniform="auc_in")

        

        self.v_new_dose_entry = LabeledEntry(row, "Liều mới (mg)", default=1000.0)

        self.v_new_dose_entry.grid(row=0, column=0, sticky="ew", padx=4)

        

        self.v_new_tau_entry = LabeledEntry(row, "Khoảng đưa liều mới - τ (h)", default=12.0)

        self.v_new_tau_entry.grid(row=0, column=1, sticky="ew", padx=4)



        ctk.CTkButton(self, text="🧮 TÍNH AUC", height=36, fg_color="#0969da", hover_color="#0550ae",

                      command=self.calc_auc).pack(fill="x", padx=6, pady=(10, 6))



        row_res = ctk.CTkFrame(self, fg_color="transparent")
        row_res.pack(fill="x", padx=6, pady=(4, 0))
        self.card_auc_result = MetricCard(row_res, "AUC kết quả (mg·h/L)")
        self.card_auc_result.pack(fill="x", padx=4, pady=4)

        # --- 6b. Dự đoán Cpred tại 1 thời điểm cụ thể với liều/τ mới ---
        ctk.CTkLabel(
            self, text="Dự đoán Cpred (liều/τ mới) — chồng chất liều: các liều ở Mục 3 + các liều "
                       "của chế độ MỚI được dùng từ sau liều cuối (Mục 3) đến thời điểm dự đoán.",
            font=FONT_SMALL, text_color=("gray40", "gray70"), wraplength=900, justify="left"
        ).pack(anchor="w", padx=6, pady=(16, 6))

        row_tinf = ctk.CTkFrame(self, fg_color="transparent")
        row_tinf.pack(fill="x", padx=6)
        self.v_new_tinf_entry = LabeledEntry(row_tinf, "Tinf mới (h)", default=1.0)
        self.v_new_tinf_entry.pack(fill="x")

        target_frame = ctk.CTkFrame(self, fg_color="transparent")
        target_frame.pack(fill="x", padx=6, pady=(10, 0))
        ctk.CTkLabel(target_frame, text="Thời điểm dự đoán (để trống = mặc định: 30 phút trước liều thứ 5 của chế độ mới)",
                     font=FONT_SMALL).pack(anchor="w")
        target_sub = ctk.CTkFrame(target_frame, fg_color="transparent")
        target_sub.pack(fill="x", pady=(2, 4))
        self.v_cpred_target_entry = ctk.CTkEntry(target_sub, placeholder_text="Để trống = mặc định")
        self.v_cpred_target_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(target_sub, text="📅", width=36, command=self.open_cpred_target_calendar).pack(side="left")

        ctk.CTkButton(self, text="🧮 TÍNH Cpred DỰ ĐOÁN", height=36, fg_color="#8250df", hover_color="#6639ba",
                      command=self.calc_cpred_prediction).pack(fill="x", padx=6, pady=(10, 6))

        row_cpred_res = ctk.CTkFrame(self, fg_color="transparent")
        row_cpred_res.pack(fill="x", padx=6, pady=(4, 0))
        self.card_cpred_predict = MetricCard(row_cpred_res, "Cpred dự đoán (μg/mL)")
        self.card_cpred_predict.pack(fill="x", padx=4, pady=4)
        self.cpred_predict_time_label = ctk.CTkLabel(
            self, text="", font=FONT_SMALL, text_color=("gray40", "gray70"), wraplength=900, justify="left")
        self.cpred_predict_time_label.pack(anchor="w", padx=6, pady=(4, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)

    def open_cpred_target_calendar(self):
        current_dt = parse_vanco_datetime(self.v_cpred_target_entry.get()) if self.v_cpred_target_entry.get().strip() else datetime.datetime.now()
        DateTimePickerWindow(self, initial_dt=current_dt, callback=lambda dt: (
            self.v_cpred_target_entry.delete(0, "end"), self.v_cpred_target_entry.insert(0, dt.strftime("%Y-%m-%d %H:%M"))))

    def calc_cpred_prediction(self):
        """Dự đoán Cpred tại 1 thời điểm cụ thể (mặc định: 30 phút trước liều thứ 5 của chế
        độ liều MỚI), theo nguyên lý chồng chất liều: các liều đã có ở Mục 3 CỘNG với các
        liều của chế độ mới được dùng từ ngay sau liều cuối (Mục 3) cho tới thời điểm dự đoán."""
        if self.bayes_result is None or not self.bayes_result.success:
            self.card_cpred_predict.set_value("Chưa chạy solve Bayes")
            self.cpred_predict_time_label.configure(text="")
            return
        if not self.dose_rows:
            self.card_cpred_predict.set_value("Chưa có liều ở Mục 3")
            return

        new_dose = self.v_new_dose_entry.get_float(1000.0)
        new_tau = self.v_new_tau_entry.get_float(12.0)
        new_tinf = self.v_new_tinf_entry.get_float(1.0)
        if new_dose <= 0 or new_tau <= 0 or new_tinf <= 0:
            self.card_cpred_predict.set_value("Giá trị không hợp lệ")
            self.cpred_predict_time_label.configure(text="")
            return

        last_dose_row = max(self.dose_rows, key=lambda r: r.get_dose().given_at)
        last_dose_time = last_dose_row.get_dose().given_at

        target_str = self.v_cpred_target_entry.get().strip()
        if target_str:
            target_time = parse_vanco_datetime(target_str)
            is_default = False
        else:
            # Mặc định: 30 phút trước liều thứ 5 của chế độ mới. Liều 1 của chế độ mới =
            # liều cuối (Mục 3) + τ_mới; liều thứ 5 = liều cuối + 5×τ_mới.
            target_time = last_dose_time + datetime.timedelta(hours=5 * new_tau) - datetime.timedelta(minutes=30)
            is_default = True

        # Sinh các liều của chế độ MỚI, bắt đầu ngay sau liều cuối (Mục 3), cách nhau τ_mới,
        # chỉ tính các liều đã thực sự "được dùng" (given_at <= thời điểm dự đoán).
        new_regimen_doses = []
        t = last_dose_time + datetime.timedelta(hours=new_tau)
        while t <= target_time and len(new_regimen_doses) < 500:
            new_regimen_doses.append(VancoDose(dose_mg=new_dose, given_at=t))
            t += datetime.timedelta(hours=new_tau)

        full_doses = self._get_doses() + new_regimen_doses
        if hasattr(self.bayes_result, "predict"):          # tucuxi.*: mô phỏng lại bằng chính engine (CL theo SCr mới nhất)
            cpred = self.bayes_result.predict(
                [target_time], extra_doses=[tue.Intake(d.given_at, d.dose_mg, new_tinf) for d in new_regimen_doses])[0]
            self.card_cpred_predict.set_value(f"{cpred:.2f} μg/mL")
            note = " (mặc định: 30 phút trước liều thứ 5 của chế độ mới)" if is_default else " (do người dùng nhập)"
            self.cpred_predict_time_label.configure(text=(
                f"⏱ Thời điểm tính: {target_time.strftime('%Y-%m-%d %H:%M')}{note} — engine Tucuxi: "
                f"{len(self._get_doses())} liều ở Mục 3 + {len(new_regimen_doses)} liều của chế độ mới."))
            return
        q = self.priors.q_prior if self.priors is not None else 6.5

        # SỬA (2026-09, xử lý AKI): dùng CL BẬC THANG từ TOÀN BỘ các lần TDM đã giải (không
        # chỉ CL của lần cuối) — mỗi đoạn quá khứ dùng đúng CL_post cố định của lần TDM đó,
        # đoạn cuối cùng (CL_post mới nhất) áp dụng cho cả liều còn lại ở Mục 3 lẫn các liều
        # của chế độ MỚI — nhất quán với cách tính OFV khi tối ưu Bayesian ở Mục E.
        # CL_post của lần TDM k = CL của khoảng (TDM k-1 → TDM k]; lần 1: từ liều đầu tiên.
        # Đoạn cuối (CL_post mới nhất) kéo dài tiếp qua các liều còn lại ở Mục 3 và cả các liều
        # của chế độ MỚI. Ranh giới = thời điểm đo của lần TDM trước (xem solve_bayesian_sequential).
        cl_segments = []
        seg_start = min(d.given_at for d in self._get_doses())
        for r in self.block_results:
            if not r.points:
                continue
            cl_segments.append((seg_start, r.CL_optimized))
            seg_start = max(p["t_obs"] for p in r.points)
        if not cl_segments:
            cl_segments = [(last_dose_time, self.bayes_result.CL_optimized)]

        cpred = compute_cpred_two_compartment_piecewise(
            cl_segments, self.bayes_result.Vc_optimized, self.bayes_result.Vp_optimized,
            q, full_doses, target_time, new_tinf)

        self.card_cpred_predict.set_value(f"{cpred:.2f} μg/mL")
        note = " (mặc định: 30 phút trước liều thứ 5 của chế độ mới)" if is_default else " (do người dùng nhập)"
        self.cpred_predict_time_label.configure(text=(
            f"⏱ Thời điểm tính: {target_time.strftime('%Y-%m-%d %H:%M')}{note} — đã cộng dồn "
            f"{len(self._get_doses())} liều ở Mục 3 + {len(new_regimen_doses)} liều của chế độ mới."))

    def calc_auc(self):

        if self.bayes_result is None or not self.bayes_result.success:

            self.card_auc_result.set_value("Chưa chạy solve Bayes")

            return

        

        new_dose = self.v_new_dose_entry.get_float(1000.0)

        new_tau = self.v_new_tau_entry.get_float(12.0)

        clbn = self.bayes_result.CL_optimized



        if new_tau <= 0 or clbn <= 0:

            self.card_auc_result.set_value("Giá trị không hợp lệ")

            return



        # Công thức yêu cầu: AUC = Liều mới x 24 / (khoảng đưa liều x Clbn)

        auc = (new_dose * 24.0) / (new_tau * clbn)

        self.card_auc_result.set_value(f"{auc:.2f} mg·h/L")



    # ---------------------------------------------------------------

    def _build_chart_section(self):

        self._section_header("7. Đồ thị đường cong nồng độ mô phỏng")

        self.v_chart_container = ctk.CTkFrame(self, fg_color=("gray95", "gray14"), corner_radius=10)

        self.v_chart_container.pack(fill="both", padx=6, pady=(6, 6))

        self.v_chart_placeholder = ctk.CTkLabel(

            self.v_chart_container,

            text="Biểu đồ sẽ xuất hiện sau khi chạy tối ưu Bayes.",

            font=FONT_SMALL, text_color=("gray40", "gray70"))

        self.v_chart_placeholder.pack(padx=20, pady=60)



        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)



    def refresh_chart(self):

        if self.bayes_result is None or not self.bayes_result.success:

            return

        r = self.bayes_result
        q = self.priors.q_prior if self.priors is not None else 6.5
        meas_list = self.measurement_used or []
        t_inf_for_curve = meas_list[0].t_inf_h if meas_list else 1.0
        t_end = (max(m.t_obs for m in meas_list) if meas_list else datetime.datetime.now()) + datetime.timedelta(hours=6)

        if hasattr(r, "predict"):
            times, concs = self._tucuxi_curve(r, meas_list)
        else:
            times, concs = simulate_concentration_curve(
                r.CL_optimized, r.Vc_optimized, r.Vp_optimized, q,
                self.doses_used, t_inf_for_curve, t_end=t_end)



        if self.chart_canvas is None:

            self.v_chart_placeholder.pack_forget()

            fig = Figure(figsize=(7.5, 4.2), dpi=100)

            self.v_chart_ax = fig.add_subplot(111)

            self.chart_canvas = FigureCanvasTkAgg(fig, master=self.v_chart_container)

            self.chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)



        ax = self.v_chart_ax

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

        self.chart_canvas.figure.tight_layout()

        self.chart_canvas.draw()



    # ---------------------------------------------------------------

    def _build_save_section(self):

        self._section_header("8. Lưu kết quả TDM Vancomycin lên Cloud")

        ctk.CTkButton(self, text="💾 Lưu kết quả lên Cloud", height=36,

                      fg_color="#2f6f4f", hover_color="#254f39",

                      command=self.save_result).pack(fill="x", padx=6, pady=(0, 4))

        self.save_status = StatusLabel(self)

        self.save_status.pack(fill="x", padx=6, pady=(0, 20))



    def _on_prev_tree_click(self, event):
        """Xử lý click chuột vào bảng lịch sử: nếu click đúng vào cột "Chọn" thì đảo
        trạng thái tick (☐ <-> ☑) của dòng đó, dùng để chọn (các) dòng cần xóa."""
        region = self.prev_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.prev_tree.identify_column(event.x)
        row_iid = self.prev_tree.identify_row(event.y)
        if not row_iid:
            return
        if col == "#1":  # Cột đầu tiên = "Chọn"
            vals = list(self.prev_tree.item(row_iid, "values"))
            vals[0] = "☑" if vals[0] == "☐" else "☐"
            self.prev_tree.item(row_iid, values=vals)

    def _get_checked_vanco_rows(self):
        """Trả về danh sách các dòng lịch sử TDM Vancomycin đang được tick chọn,
        mỗi phần tử là dict {"tdm_date": ..., "msyt": ...}."""
        checked = []
        for iid in self.prev_tree.get_children():
            vals = self.prev_tree.item(iid, "values")
            if vals and vals[0] == "☑":
                meta = self._vanco_row_meta.get(iid)
                if meta:
                    checked.append(meta)
        return checked

    def delete_selected_vanco_rows(self):
        """Xóa (các) dòng lịch sử TDM Vancomycin đã được tick chọn trên Cloud (bảng
        vanco_results_history), sau khi người dùng xác nhận 2 lần (theo yêu cầu)."""
        checked = self._get_checked_vanco_rows()
        if not checked:
            self.vanco_delete_status.show("⚠️ Chưa chọn dòng dữ liệu nào để xóa (tick vào cột \"Chọn\").",
                                           "warning")
            return

        dates_str = "\n".join(f"  • {row['tdm_date']}" for row in checked)
        confirm1 = messagebox.askyesno(
            "Xác nhận xóa",
            f"Bạn sắp xóa {len(checked)} lần TDM Vancomycin của bệnh nhân "
            f"{self._vanco_loaded_msyt} vào (các) ngày:\n{dates_str}\n\nTiếp tục?"
        )
        if not confirm1:
            return

        confirm2 = messagebox.askyesno(
            "Xác nhận lần cuối",
            "⚠️ Hành động này KHÔNG THỂ HOÀN TÁC. Dữ liệu sẽ bị xóa vĩnh viễn trên Cloud.\n\n"
            "Bạn có chắc chắn muốn xóa?"
        )
        if not confirm2:
            return

        ok_count, fail_msgs = 0, []
        for row in checked:
            ok, msg = db.delete_vanco_result_block(row["msyt"], row["tdm_date"], row.get("method"))
            if ok:
                ok_count += 1
            else:
                fail_msgs.append(f"{row['tdm_date']}: {msg}")

        if ok_count and not fail_msgs:
            self.vanco_delete_status.show(f"✅ Đã xóa thành công {ok_count} dòng dữ liệu.", "success")
        elif ok_count and fail_msgs:
            self.vanco_delete_status.show(
                f"⚠️ Đã xóa {ok_count} dòng, còn {len(fail_msgs)} dòng lỗi: " + "; ".join(fail_msgs),
                "warning")
        else:
            self.vanco_delete_status.show("❌ Xóa thất bại: " + "; ".join(fail_msgs), "error")

        # Tải lại lịch sử để đồng bộ với dữ liệu mới nhất trên Cloud
        self.load_patient_vanco()

    def save_result(self):

        """

        Lưu kết quả TDM Vancomycin lên Cloud, TÁCH RIÊNG 2 loại dữ liệu theo đúng yêu cầu:

        1) Thông tin bệnh nhân + chế độ liều dùng (Mục 1 & 3) -> CHỈ LƯU BẢN MỚI NHẤT

        2) Kết quả của lần chạy Bayes này (Mục 5, gồm cả AUC hiện tại) -> LUÔN THÊM MỚI

        """

        msyt_input = self.v_msyt_entry.get().strip()

        if not msyt_input:

            self.save_status.show("⚠️ Vui lòng nhập MSYT.", "error")

            return

        if self.bayes_result is None or not self.bayes_result.success:

            self.save_status.show("⚠️ Vui lòng chạy tối ưu Bayes trước khi lưu.", "warning")

            return



        method = self.method_var.get()
        age_v = self.v_age_entry.get_float(50.0)
        gender_v = self.v_gender_opt.get()
        height_v = self.v_height_entry.get_float(165.0)
        weight_v = self.v_weight_entry.get_float(60.0)
        scr_v = self._get_representative_scr()
        collin_like = method in ("Collin 2019", "tucuxi.collin")
        is_dialysis_v = int(self.v_dialysis_check.get()) if (not collin_like and method not in ("tucuxi.thomson", "tucuxi.yamamoto")) else 0
        is_malignancy_v = int(self.v_malignancy_check.get()) if collin_like else 0
        is_heelprick_v = int(self.v_heelprick_check.get()) if method == "Collin 2019" else 0
        if method == "tucuxi.yamamoto":                 # cờ Gram dương lưu tạm ở cột is_heelprick
            is_heelprick_v = int(self.v_gpos_check.get())

        r = self.bayes_result
        m = self.measurement_used[-1]  # điểm đo gần nhất của lần TDM cuối cùng — đại diện lưu vào lịch sử
        date_str = m.t_obs.strftime("%Y-%m-%d")
        doses_payload = [{"dose_mg": d.dose_mg, "given_at": d.given_at.strftime("%Y-%m-%d %H:%M")}
                          for d in self.doses_used]
        scr_payload = [{"scr": v, "unit": u, "measured_at": dt.strftime("%Y-%m-%d %H:%M")}
                       for v, u, dt in (r.get_raw() for r in self.scr_rows)]
        meas_payload = [{"c_obs": mm.c_obs, "t_obs": mm.t_obs.strftime("%Y-%m-%d %H:%M"), "t_inf_h": mm.t_inf_h}
                        for mm in self._get_measurements()]

        # Đảm bảo AUC hiện tại đã được tính theo dữ liệu mới nhất trước khi lưu
        auc_current = self.calc_auc_current()

        # Liều/τ "đang dùng" của lần TDM này = liều neo (kề trước các điểm đo của block cuối) —
        # dùng đúng logic đã có ở calc_auc_current() để lưu kèm vào lịch sử, phục vụ Tab 2.
        anchor_dose = getattr(r, "anchor_dose", None)
        anchor_row = self._find_dose_row_for(anchor_dose)
        if anchor_row is None and self.dose_rows:
            anchor_row = max(self.dose_rows, key=lambda row: row.get_dose().given_at)
        dose_used = anchor_row.get_dose().dose_mg if anchor_row else None
        tau_used = anchor_row.get_tau() if anchor_row else None

        # --- 1) Thông tin bệnh nhân + chế độ liều dùng: CHỈ LƯU/GHI ĐÈ BẢN MỚI NHẤT ---
        ok1, msg1 = db.save_vanco_patient_current(
            msyt=msyt_input,
            age=age_v, gender=gender_v, height=height_v,
            weight=weight_v, scr=scr_v, is_dialysis=is_dialysis_v,
            doses_json=doses_payload,
            method=method, is_malignancy=is_malignancy_v, is_heelprick=is_heelprick_v,
            scr_json=scr_payload, measurements_json=meas_payload,
        )

        # --- 2) Kết quả lần TDM này: LUÔN THÊM MỚI vào lịch sử, không ghi đè ---
        ok2, msg2 = db.save_vanco_result_history(
            msyt=msyt_input, tdm_date=date_str,
            q_prior=self.priors.q_prior if self.priors else None,
            cl_prior=self.priors.cl_prior if self.priors else None,
            vc_prior=self.priors.vc_prior if self.priors else None,
            vp_prior=self.priors.vp_prior if self.priors else None,
            c_obs=m.c_obs, t_obs=m.t_obs.strftime("%Y-%m-%d %H:%M"), t_inf=m.t_inf_h,
            cl_optimized=r.CL_optimized, vc_optimized=r.Vc_optimized, vp_optimized=r.Vp_optimized,
            c_pred_final=r.C_pred_final, ofv_final=r.OFV_final,
            auc_current=auc_current,
            method=method,
            dose_used=dose_used, tau_used=tau_used,
        )



        if ok1 and ok2:

            self.save_status.show(

                "✅ Đã lưu bản mới nhất (thông tin BN + liều dùng) và thêm mới vào lịch sử kết quả TDM.",

                "success")

        else:

            combined = "; ".join([msg for ok, msg in [(ok1, msg1), (ok2, msg2)] if not ok])

            self.save_status.show(f"⚠️ Lưu chưa trọn vẹn: {combined}", "error")

    # ===================================================================================
    # 9. Tính Bayes hàng loạt từ file Excel (bốn mô hình tucuxi.*)
    # ===================================================================================
    def _build_batch_section(self):
        if tue is None or tub is None:
            return
        import threading  # noqa: F401  (dùng trong _batch_run)
        self._section_header("9. Tính Bayes hàng loạt từ file Excel (mô hình tucuxi.*)")
        ctk.CTkLabel(
            self, justify="left", wraplength=900, font=FONT_SMALL, text_color=("gray40", "gray70"),
            text=("Nhập nhiều bệnh nhân cùng lúc theo mẫu Excel (sheet 'data dữ liệu', dữ liệu từ hàng 3: tuổi nam cột B / nữ cột C, "
                  "cân nặng D, chiều cao E; dòng liều: Từ F, Đến G, liều mg H, τ(h) I, thời gian truyền(h) J; dòng xét nghiệm: "
                  "thời điểm F, SCr μmol/L K, nồng độ M). Kết quả: rBias/APE từng lần TDM và thống kê rRMSE, MdAPE, P20/P30 theo mô hình.")
        ).pack(anchor="w", padx=6, pady=(0, 6))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=(0, 6))
        self.batch_path_var = ctk.StringVar(value="")
        ctk.CTkEntry(row, textvariable=self.batch_path_var,
                     placeholder_text="Đường dẫn file Excel đầu vào...").pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(row, text="📂 Chọn file", width=110, command=self._batch_pick_file).pack(side="left")
        mrow = ctk.CTkFrame(self, fg_color="transparent")
        mrow.pack(fill="x", padx=6, pady=(0, 4))
        self.batch_model_vars = {}
        for key in tue.MODEL_FILES:
            var = ctk.BooleanVar(value=True)
            self.batch_model_vars[key] = var
            ctk.CTkCheckBox(mrow, text=key, variable=var, width=130).pack(side="left", padx=(0, 10))
        orow = ctk.CTkFrame(self, fg_color="transparent")
        orow.pack(fill="x", padx=6, pady=(0, 4))
        self.batch_cumulative_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(orow, variable=self.batch_cumulative_var,
                        text="Khớp CỘNG DỒN (dùng mọi nồng độ đến lần TDM N). Bỏ chọn = chỉ nồng độ lần N, như bộ dữ liệu mẫu Tucuxi"
                        ).pack(anchor="w")
        self.batch_gpos_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(orow, variable=self.batch_gpos_var,
                        text="Yamamoto: coi bệnh nhân nhiễm khuẩn Gram dương (mặc định của file .tdd)").pack(anchor="w", pady=(4, 0))
        self.batch_btn = ctk.CTkButton(self, text="▶ CHẠY HÀNG LOẠT & XUẤT EXCEL", height=38, fg_color="#8250df",
                                       hover_color="#6639ba", command=self._batch_run)
        self.batch_btn.pack(fill="x", padx=6, pady=(4, 4))
        self.batch_progress = ctk.CTkProgressBar(self)
        self.batch_progress.set(0)
        self.batch_progress.pack(fill="x", padx=6, pady=(0, 4))
        self.batch_status = StatusLabel(self)
        self.batch_status.pack(fill="x", padx=6, pady=(0, 20))

    def _batch_pick_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Chọn file Excel đầu vào", filetypes=[("Excel", "*.xlsx *.xlsm")])
        if path:
            self.batch_path_var.set(path)

    def _batch_run(self):
        import threading
        from tkinter import filedialog
        src = self.batch_path_var.get().strip()
        if not src:
            self.batch_status.show("⚠️ Hãy chọn file Excel đầu vào.", "warning")
            return
        models = [k for k, v in self.batch_model_vars.items() if v.get()]
        if not models:
            self.batch_status.show("⚠️ Hãy chọn ít nhất 1 mô hình.", "warning")
            return
        out = filedialog.asksaveasfilename(
            title="Lưu kết quả Excel", defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialfile=f"ketqua_tucuxi_{datetime.datetime.now():%Y%m%d_%H%M}.xlsx")
        if not out:
            return
        cumulative, gpos = bool(self.batch_cumulative_var.get()), bool(self.batch_gpos_var.get())
        self.batch_btn.configure(state="disabled")
        self.batch_progress.set(0)
        self.batch_status.show("⏳ Đang tính... (có thể mất vài phút với nhiều bệnh nhân)", "info")

        def progress(done, total, label):
            self.after(0, lambda: (self.batch_progress.set(done / max(total, 1)),
                                   self.batch_status.show(f"⏳ {done}/{total} — {label}", "info")))

        def worker():
            try:
                res = tub.run_batch(src, out, models=models, cumulative=cumulative, gram_positive=gpos, progress=progress)
                lines = []
                for m, summ in res["summary"].items():
                    s2 = summ.get("Bayes N−1→N (TDM ≥ 2)", {})
                    s1 = summ.get("Tiên nghiệm (TDM 1)", {})
                    lines.append(f"{m}: rRMSE tiên nghiệm {s1.get('rrmse', float('nan')):.1f}% (n={s1.get('n', 0)}), "
                                 f"N−1→N {s2.get('rrmse', float('nan')):.1f}% (n={s2.get('n', 0)})")
                msg = (f"✅ Xong {res['n_cases']} bệnh nhân (bỏ qua {res['n_skipped']}). Đã lưu: {out}\n" + "\n".join(lines))
                self.after(0, lambda: (self.batch_status.show(msg, "success"), self.batch_progress.set(1)))
            except Exception as exc:
                self.after(0, lambda e=exc: self.batch_status.show(f"❌ Lỗi tính hàng loạt: {e}", "error"))
            finally:
                self.after(0, lambda: self.batch_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

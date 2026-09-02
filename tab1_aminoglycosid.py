"""
tab1_aminoglycosid.py — Tab "Tính toán & TDM" cho Aminoglycosid (liều đầu tiên, cá thể hóa
Mục 3, hiệu chỉnh liều Mục 4, biểu đồ mô phỏng, xuất PDF).

Tách riêng khỏi app.py để phát triển/bảo trì độc lập với các tab khác (Vancomycin, CSDL...).
Toàn bộ logic tính toán PK vẫn nằm nguyên trong pk_calculations.py — file này CHỈ chứa UI.
"""

from tkinter import ttk, messagebox, filedialog

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
    parse_date, today_str, clean_vn_text,
    LabeledEntry, LabeledOption, LabeledCheck, MetricCard, StatusLabel,
)


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

        self._build_section2_population()

        self._build_section3_individual()

        self._build_section4_adjustment()

        self._build_section5_chart()

        self._build_section6_pdf()



        self.recalc_population()



    # ---------------------------------------------------------------

    def _section_header(self, text):

        ctk.CTkLabel(self, text=text, font=FONT_H2).pack(anchor="w", padx=6, pady=(18, 6))



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

        self._section_header("2. Thông số quần thể tham khảo")

        row = ctk.CTkFrame(self, fg_color="transparent")

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

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)



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

        self._section_header("3. Cá thể hoá theo kết quả TDM")

        row1 = ctk.CTkFrame(self, fg_color="transparent")

        row1.pack(fill="x", padx=6)

        row1.grid_columnconfigure((0, 1), weight=1, uniform="s3a")

        self.tdm_date_entry = LabeledEntry(row1, "Ngày thực hiện TDM (YYYY-MM-DD)", default=today_str())

        self.tdm_date_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.current_scr_entry = LabeledEntry(row1, "Scr ngày TDM (μmol/L)", default=80.0)

        self.current_scr_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))



        self.is_first_dose_check = LabeledCheck(self, "Liều ĐẦU TIÊN (chưa tích luỹ)", default=False)

        self.is_first_dose_check.pack(anchor="w", padx=6, pady=(4, 0))



        self.dose_given_entry = LabeledEntry(self, "Tổng liều đã dùng khi lấy mẫu (mg)", default=0.0)

        self.dose_given_entry.pack(fill="x", padx=6)

        self.dose_given_entry.var.trace_add("write", lambda *a: setattr(self, "_dose_given_touched", True))



        self.tau_sampling_entry = LabeledEntry(self, "Khoảng đưa liều (τ) lúc lấy mẫu (h)", default=24.0)

        self.tau_sampling_entry.pack(fill="x", padx=6)

        self.tau_sampling_entry.var.trace_add("write", lambda *a: setattr(self, "_tau_sampling_touched", True))



        row2 = ctk.CTkFrame(self, fg_color="transparent")

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



        ctk.CTkButton(self, text="🧮 TÍNH TOÁN CÁ THỂ HÓA", height=36,

                      command=self.calc_section3).pack(fill="x", padx=6, pady=(12, 6))

        self.sec3_status = StatusLabel(self)

        self.sec3_status.pack(fill="x", padx=6)



        row3 = ctk.CTkFrame(self, fg_color="transparent")

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



        ctk.CTkButton(self, text="💾 Xác nhận & Lưu lên Cloud (Mục 3)", height=36,

                      fg_color="#2f6f4f", hover_color="#254f39",

                      command=self.save_section3).pack(fill="x", padx=6, pady=(12, 4))

        self.save3_status = StatusLabel(self)

        self.save3_status.pack(fill="x", padx=6)



        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)



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

        self._section_header("4. Hiệu chỉnh liều theo TDM")

        row = ctk.CTkFrame(self, fg_color="transparent")

        row.pack(fill="x", padx=6)

        row.grid_columnconfigure((0, 1, 2), weight=1, uniform="s4")

        self.new_dose_entry = LabeledEntry(row, "Liều mới - Dose (mg)", default=400.0)

        self.new_dose_entry.grid(row=0, column=0, sticky="ew", padx=4)

        self.new_tau_entry = LabeledEntry(row, "Khoảng đưa liều mới - τ (h)", default=36.0)

        self.new_tau_entry.grid(row=0, column=1, sticky="ew", padx=4)

        self.new_t_inf_entry = LabeledEntry(row, "Thời gian truyền mới - t' (h)", default=1.0)

        self.new_t_inf_entry.grid(row=0, column=2, sticky="ew", padx=4)



        ctk.CTkButton(self, text="🧮 TÍNH TOÁN LIỀU MỚI", height=36,

                      command=self.calc_section4).pack(fill="x", padx=6, pady=(12, 6))

        self.sec4_status = StatusLabel(self)

        self.sec4_status.pack(fill="x", padx=6)



        row2 = ctk.CTkFrame(self, fg_color="transparent")

        row2.pack(fill="x", padx=6, pady=(8, 0))

        row2.grid_columnconfigure((0, 1), weight=1, uniform="n")

        self.card_cp_pred = MetricCard(row2, "C'p dự đoán SS (μg/mL)")

        self.card_cp_pred.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        self.card_ctr_pred = MetricCard(row2, "C'tr dự đoán SS (μg/mL)")

        self.card_ctr_pred.grid(row=0, column=1, sticky="ew", padx=4, pady=4)



        ctk.CTkButton(self, text="💾 Xác nhận & Lưu lên Cloud (Mục 4)", height=36,

                      fg_color="#2f6f4f", hover_color="#254f39",

                      command=self.save_section4).pack(fill="x", padx=6, pady=(12, 4))

        self.save4_status = StatusLabel(self)

        self.save4_status.pack(fill="x", padx=6)



        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)



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

        self._section_header("5. Đồ thị nồng độ qua nhiều chu kỳ liều")

        row = ctk.CTkFrame(self, fg_color="transparent")

        row.pack(fill="x", padx=6)

        ctk.CTkLabel(row, text="Số chu kỳ:", font=FONT_SMALL).pack(side="left", padx=(0, 10))

        self.num_cycles_var = ctk.IntVar(value=10)

        self.num_cycles_label = ctk.CTkLabel(row, text="10", font=FONT_SMALL, width=30)

        slider = ctk.CTkSlider(row, from_=2, to=20, number_of_steps=18,

                                variable=self.num_cycles_var, command=self._on_slider_change)

        slider.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.num_cycles_label.pack(side="left")



        self.chart_container = ctk.CTkFrame(self, fg_color=("gray95", "gray14"), corner_radius=10)

        self.chart_container.pack(fill="both", padx=6, pady=(10, 6))

        self.chart_placeholder = ctk.CTkLabel(

            self.chart_container,

            text="Biểu đồ sẽ xuất hiện sau khi bạn hoàn thành Mục 3 và Mục 4.",

            font=FONT_SMALL, text_color=("gray40", "gray70"))

        self.chart_placeholder.pack(padx=20, pady=60)

        self.chart_canvas = None



        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)



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

        ctk.CTkLabel(self, text="📄 Xuất báo cáo hội chẩn TDM (PDF) theo CSDL bệnh nhân",

                     font=FONT_H2).pack(anchor="w", padx=6, pady=(4, 6))

        ctk.CTkButton(self, text="📥 Tạo và Lưu file báo cáo PDF từ CSDL", height=36,

                      command=self.export_pdf).pack(fill="x", padx=6, pady=(0, 4))

        self.pdf_status = StatusLabel(self)

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





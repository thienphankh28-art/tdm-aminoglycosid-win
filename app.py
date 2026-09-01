"""
app.py — Giao diện phần mềm TDM Aminoglycosid (CustomTkinter Desktop App)

Chuyển đổi hoàn toàn từ Streamlit sang ứng dụng Desktop Windows (Native App)
bằng CustomTkinter. Toàn bộ logic gọi hàm từ database.py (Supabase Cloud) và
pk_calculations.py (Dược động học) được GIỮ NGUYÊN 100%, không chỉnh sửa.
"""

import os
import json
import datetime
import unicodedata
from tkinter import ttk, messagebox, filedialog

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
from vanco_calculations import (
    VancoPatientInfo, VancoDose, VancoMeasurement,
    compute_population_priors, solve_bayesian_posterior,
    simulate_concentration_curve,
)

# =============================================================================
# CẤU HÌNH GIAO DIỆN CHUNG
# =============================================================================
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

COPYRIGHT_EMAIL = "thienphankh28@gmail.com"
DEFAULT_VERSION = "V.1.0.8"

FONT_H1 = ("Segoe UI", 20, "bold")
FONT_H2 = ("Segoe UI", 15, "bold")
FONT_NORMAL = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 11)


# =============================================================================
# HÀM TIỆN ÍCH DÙNG CHUNG
# =============================================================================
def parse_float(value, default=0.0):
    """Chuyển chuỗi nhập từ Entry thành float an toàn (tương đương st.number_input)"""
    try:
        return float(str(value).replace(",", ".").strip())
    except Exception:
        return default


def clean_vn_text(text):
    """Loại bỏ dấu tiếng Việt để xuất PDF bằng font Arial chuẩn của FPDF"""
    if text is None:
        return ""
    nfkd_form = unicodedata.normalize("NFKD", str(text))
    result = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return result.replace("đ", "d").replace("Đ", "D")


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def parse_date(value):
    """Parse chuỗi ngày dạng YYYY-MM-DD, trả về datetime.date; lỗi -> hôm nay"""
    try:
        return datetime.datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        return datetime.date.today()


# =============================================================================
# CÁC WIDGET TÁI SỬ DỤNG (thay thế st.number_input / st.metric / ...)
# =============================================================================
class LabeledEntry(ctk.CTkFrame):
    """Nhãn + ô nhập liệu, tương đương st.number_input / st.text_input"""

    def __init__(self, master, label, default="", **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        ctk.CTkLabel(self, text=label, anchor="w", font=FONT_SMALL,
                     text_color=("gray20", "gray85")).pack(anchor="w")
        self.var = ctk.StringVar(value=str(default))
        self.entry = ctk.CTkEntry(self, textvariable=self.var)
        self.entry.pack(fill="x", pady=(2, 4))

    def get(self):
        return self.var.get()

    def get_float(self, default=0.0):
        return parse_float(self.var.get(), default)

    def set(self, value):
        self.var.set("" if value is None else str(value))


class LabeledOption(ctk.CTkFrame):
    """Nhãn + Combobox, tương đương st.selectbox"""

    def __init__(self, master, label, values, default=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        ctk.CTkLabel(self, text=label, anchor="w", font=FONT_SMALL,
                     text_color=("gray20", "gray85")).pack(anchor="w")
        self.var = ctk.StringVar(value=default or values[0])
        self.combo = ctk.CTkOptionMenu(self, values=values, variable=self.var)
        self.combo.pack(fill="x", pady=(2, 4))

    def get(self):
        return self.var.get()

    def set(self, value):
        if value:
            self.var.set(value)


class LabeledCheck(ctk.CTkFrame):
    """Checkbox có nhãn, tương đương st.checkbox"""

    def __init__(self, master, label, default=False, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.var = ctk.BooleanVar(value=bool(default))
        self.check = ctk.CTkCheckBox(self, text=label, variable=self.var, font=FONT_SMALL)
        self.check.pack(anchor="w", pady=4)

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(bool(value))


class MetricCard(ctk.CTkFrame):
    """Thẻ hiển thị số liệu, tương đương st.metric()"""

    def __init__(self, master, title, value="--", **kwargs):
        super().__init__(master, corner_radius=10, fg_color=("gray92", "gray17"), **kwargs)
        ctk.CTkLabel(self, text=title, font=FONT_SMALL,
                     text_color=("gray40", "gray70")).pack(anchor="w", padx=12, pady=(8, 0))
        self.value_label = ctk.CTkLabel(self, text=value, font=("Segoe UI", 18, "bold"))
        self.value_label.pack(anchor="w", padx=12, pady=(0, 10))

    def set_value(self, value):
        self.value_label.configure(text=value)


class StatusLabel(ctk.CTkLabel):
    """Nhãn hiển thị thông báo success/error/warning/info thay cho st.success/error..."""

    COLORS = {
        "success": "#1a7f37",
        "error": "#d1242f",
        "warning": "#9a6700",
        "info": "#0969da",
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, text="", font=FONT_SMALL, justify="left",
                          anchor="w", wraplength=560, **kwargs)

    def show(self, message, kind="info"):
        self.configure(text=message, text_color=self.COLORS.get(kind, "#0969da"))


# =============================================================================
# MÀN HÌNH ĐĂNG NHẬP
# =============================================================================
class LoginFrame(ctk.CTkFrame):
    def __init__(self, master, on_success):
        super().__init__(master, fg_color="transparent")
        self.on_success = on_success

        card = ctk.CTkFrame(self, corner_radius=16, width=420)
        card.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(card, text="🔐 Đăng nhập hệ thống", font=FONT_H1).pack(padx=40, pady=(36, 4))
        ctk.CTkLabel(card, text="TDM Aminoglycosid — Vui lòng đăng nhập bằng tài khoản\nđược cấp trên hệ thống Cloud.",
                     font=FONT_SMALL, text_color=("gray40", "gray70"), justify="center").pack(padx=40, pady=(0, 20))

        self.user_entry = LabeledEntry(card, "Tên đăng nhập")
        self.user_entry.pack(fill="x", padx=40, pady=(0, 6))

        ctk.CTkLabel(card, text="Mật khẩu", anchor="w", font=FONT_SMALL,
                     text_color=("gray20", "gray85")).pack(anchor="w", padx=40)
        self.pass_var = ctk.StringVar()
        self.pass_entry = ctk.CTkEntry(card, textvariable=self.pass_var, show="•")
        self.pass_entry.pack(fill="x", padx=40, pady=(2, 10))
        self.pass_entry.bind("<Return>", lambda e: self.try_login())

        self.status = StatusLabel(card)
        self.status.pack(fill="x", padx=40, pady=(0, 6))

        ctk.CTkButton(card, text="Đăng nhập", command=self.try_login,
                      height=38, font=FONT_H2).pack(fill="x", padx=40, pady=(6, 36))

    def try_login(self):
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()
        if not username or not password:
            self.status.show("⚠️ Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.", "warning")
            return
        user_data = db.check_login(username, password)
        if user_data:
            fullname, role = user_data
            self.status.show(f"✅ Đăng nhập thành công! Xin chào bác sĩ/dược sĩ {fullname}.", "success")
            self.on_success(username, fullname, role)
        else:
            self.status.show("❌ Tên đăng nhập, mật khẩu không đúng hoặc chưa kết nối được Cloud!", "error")


# =============================================================================
# TAB 1 — TÍNH TOÁN & TDM
# =============================================================================
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


# =============================================================================
# TAB 2 — QUẢN LÝ BỆNH NHÂN TRÊN CLOUD
# =============================================================================
class Tab2DatabaseFrame(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.current_msyt = None
        self.history_dates = []

        outer = ctk.CTkScrollableFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True)

        ctk.CTkLabel(outer, text="Tra cứu & Quản lý CSDL Bệnh nhân trên Cloud",
                     font=FONT_H2).pack(anchor="w", padx=6, pady=(6, 8))

        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.pack(fill="x", padx=6)
        self.lookup_entry = LabeledEntry(row, "Nhập MSYT để tra cứu thông tin và quản lý lịch sử TDM")
        self.lookup_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(row, text="Tra cứu", width=120, command=self.lookup).pack(side="left", pady=(18, 4))
        self.lookup_status = StatusLabel(outer)
        self.lookup_status.pack(fill="x", padx=6, pady=(6, 0))

        ctk.CTkLabel(outer, text="Thông tin hành chính bệnh nhân", font=FONT_SMALL,
                     text_color=("gray30", "gray75")).pack(anchor="w", padx=6, pady=(14, 4))
        self.patient_tree = self._make_treeview(outer)

        ctk.CTkLabel(outer, text="Lịch sử các Block TDM", font=FONT_SMALL,
                     text_color=("gray30", "gray75")).pack(anchor="w", padx=6, pady=(14, 4))
        self.history_tree = self._make_treeview(outer, height=6)

        delete_box = ctk.CTkFrame(outer, corner_radius=10, fg_color=("gray95", "gray14"))
        delete_box.pack(fill="x", padx=6, pady=(14, 4))
        ctk.CTkLabel(delete_box, text="🗑️ Tùy chọn xóa dữ liệu trên Cloud", font=FONT_SMALL,
                     text_color=("gray20", "gray85")).pack(anchor="w", padx=14, pady=(12, 6))

        del_row = ctk.CTkFrame(delete_box, fg_color="transparent")
        del_row.pack(fill="x", padx=14)
        self.date_option_var = ctk.StringVar(value="—")
        self.date_option = ctk.CTkOptionMenu(del_row, values=["—"], variable=self.date_option_var, width=180)
        self.date_option.pack(side="left")
        ctk.CTkButton(del_row, text="Xóa Block TDM ngày này", fg_color="#b54708", hover_color="#8a3505",
                      command=self.delete_block).pack(side="left", padx=(10, 0))

        ctk.CTkLabel(delete_box,
                     text="⚠️ Thao tác dưới đây sẽ xóa vĩnh viễn thông tin và toàn bộ lịch sử TDM "
                          "của bệnh nhân này trên Cloud!",
                     font=FONT_SMALL, text_color="#9a6700", wraplength=700, justify="left"
                     ).pack(anchor="w", padx=14, pady=(12, 6))
        ctk.CTkButton(delete_box, text="Xóa toàn bộ Bệnh nhân này", fg_color="#d1242f", hover_color="#a01c24",
                      command=self.delete_patient).pack(anchor="w", padx=14, pady=(0, 14))

        self.delete_status = StatusLabel(outer)
        self.delete_status.pack(fill="x", padx=6)

        ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=6, pady=16)

        ctk.CTkLabel(outer, text="📈 Biểu đồ xu hướng TDM theo bệnh nhân", font=FONT_H2).pack(
            anchor="w", padx=6, pady=(0, 8))
        self.trend_container = ctk.CTkFrame(outer, fg_color="transparent")
        self.trend_container.pack(fill="both", expand=True, padx=6)
        self.trend_placeholder = ctk.CTkLabel(
            self.trend_container,
            text="Vui lòng nhập MSYT ở ô tra cứu phía trên để xem biểu đồ xu hướng.",
            font=FONT_SMALL, text_color=("gray40", "gray70"))
        self.trend_placeholder.pack(padx=20, pady=40)
        self.trend_canvas_drug = None
        self.trend_canvas_dose = None

    def _make_treeview(self, master, height=5):
        frame = ctk.CTkFrame(master, fg_color="transparent")
        frame.pack(fill="x", padx=6, pady=(0, 6))
        tree = ttk.Treeview(frame, show="headings", height=height)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        return tree

    def _fill_treeview(self, tree, df):
        tree.delete(*tree.get_children())
        tree["columns"] = list(df.columns) if not df.empty else []
        for col in tree["columns"]:
            tree.heading(col, text=col)
            tree.column(col, width=110, anchor="center")
        for _, row in df.iterrows():
            tree.insert("", "end", values=list(row.values))

    def lookup(self):
        msyt = self.lookup_entry.get().strip()
        self.current_msyt = msyt
        if not msyt:
            self.lookup_status.show("⚠️ Vui lòng nhập MSYT.", "warning")
            return

        df_patient = db.get_patient_by_msyt(msyt)
        df_history = db.get_history_by_msyt(msyt)

        if not df_patient.empty:
            self._fill_treeview(self.patient_tree, df_patient)
            self.lookup_status.show(f"✅ Đã tìm thấy bệnh nhân {msyt}.", "success")
            if not df_history.empty:
                self._fill_treeview(self.history_tree, df_history)
                self.history_dates = df_history["tdm_date"].tolist()
                self.date_option.configure(values=[str(d) for d in self.history_dates])
                self.date_option_var.set(str(self.history_dates[0]))
            else:
                self._fill_treeview(self.history_tree, db.pd.DataFrame())
                self.history_dates = []
                self.date_option.configure(values=["—"])
                self.date_option_var.set("—")
                self.lookup_status.show("ℹ️ Bệnh nhân này chưa có lịch sử TDM trên Cloud.", "info")
        else:
            self._fill_treeview(self.patient_tree, db.pd.DataFrame())
            self._fill_treeview(self.history_tree, db.pd.DataFrame())
            self.history_dates = []
            self.lookup_status.show("❌ Không tìm thấy bệnh nhân với MSYT vừa nhập trên Cloud.", "error")

        self._refresh_trend(msyt)

    def delete_block(self):
        if not self.current_msyt or self.date_option_var.get() == "—":
            self.delete_status.show("⚠️ Không có block TDM nào được chọn.", "warning")
            return
        date_sel = self.date_option_var.get()
        if messagebox.askyesno("Xác nhận xóa", f"Xóa block TDM ngày {date_sel} của bệnh nhân {self.current_msyt}?"):
            ok, msg = db.delete_tdm_block(self.current_msyt, date_sel)
            self.delete_status.show(("✅ " if ok else "❌ ") + msg, "success" if ok else "error")
            self.lookup()

    def delete_patient(self):
        if not self.current_msyt:
            self.delete_status.show("⚠️ Không có bệnh nhân nào được chọn.", "warning")
            return
        if messagebox.askyesno("Xác nhận xóa vĩnh viễn",
                                f"⚠️ Xóa TOÀN BỘ hồ sơ và lịch sử TDM của bệnh nhân {self.current_msyt}?\n"
                                f"Thao tác này không thể hoàn tác!"):
            ok, msg = db.delete_patient(self.current_msyt)
            self.delete_status.show(("✅ " if ok else "❌ ") + msg, "success" if ok else "error")
            self.lookup()

    def _refresh_trend(self, msyt):
        try:
            response = db.supabase.table("tdm_history").select("*").eq("msyt", msyt).execute()
            df = db.pd.DataFrame(response.data) if response.data else db.pd.DataFrame()
        except Exception as e:
            self.delete_status.show(f"❌ Lỗi khi tải dữ liệu từ Supabase: {e}", "error")
            df = db.pd.DataFrame()

        for child in self.trend_container.winfo_children():
            child.destroy()
        self.trend_canvas_drug = None
        self.trend_canvas_dose = None

        if df.empty:
            ctk.CTkLabel(self.trend_container, text="Không có bản ghi TDM nào để vẽ biểu đồ cho MSYT này.",
                         font=FONT_SMALL, text_color=("gray40", "gray70")).pack(padx=20, pady=40)
            return

        df_sorted = df.sort_values("tdm_date")
        self.trend_container.grid_columnconfigure((0, 1), weight=1)

        # Biểu đồ nồng độ thực tế (Peak/Trough)
        left = ctk.CTkFrame(self.trend_container, fg_color=("gray95", "gray14"), corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=6)
        ctk.CTkLabel(left, text=f"Nồng độ thuốc thực tế (MSYT: {msyt})", font=FONT_SMALL).pack(pady=(8, 0))
        if "true_peak" in df_sorted.columns and "true_trough" in df_sorted.columns:
            fig1 = Figure(figsize=(5, 3.6), dpi=100)
            ax1 = fig1.add_subplot(111)
            ax1.plot(df_sorted["tdm_date"], df_sorted["true_peak"], "o-", color="red", label="C đỉnh thực tế (Peak)")
            ax1.plot(df_sorted["tdm_date"], df_sorted["true_trough"], "o-", color="blue", label="C đáy thực tế (Trough)")
            ax1.set_xlabel("Ngày TDM")
            ax1.set_ylabel("Nồng độ (µg/mL)")
            ax1.legend(fontsize=7)
            ax1.tick_params(axis="x", rotation=30, labelsize=7)
            fig1.tight_layout()
            self.trend_canvas_drug = FigureCanvasTkAgg(fig1, master=left)
            self.trend_canvas_drug.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        else:
            ctk.CTkLabel(left, text="Chưa có dữ liệu nồng độ đỉnh/đáy thực tế.",
                         font=FONT_SMALL, text_color=("gray40", "gray70")).pack(padx=20, pady=40)

        # Biểu đồ liều mới khuyến nghị
        right = ctk.CTkFrame(self.trend_container, fg_color=("gray95", "gray14"), corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=6)
        ctk.CTkLabel(right, text=f"Liều mới khuyến nghị (MSYT: {msyt})", font=FONT_SMALL).pack(pady=(8, 0))
        if "new_dose" in df_sorted.columns:
            fig2 = Figure(figsize=(5, 3.6), dpi=100)
            ax2 = fig2.add_subplot(111)
            ax2.plot(df_sorted["tdm_date"], df_sorted["new_dose"], "o-", color="green", label="Liều mới (mg)")
            ax2.set_xlabel("Ngày TDM")
            ax2.set_ylabel("Liều (mg)")
            ax2.legend(fontsize=7)
            ax2.tick_params(axis="x", rotation=30, labelsize=7)
            fig2.tight_layout()
            self.trend_canvas_dose = FigureCanvasTkAgg(fig2, master=right)
            self.trend_canvas_dose.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        else:
            ctk.CTkLabel(right, text="Chưa có thông tin liều mới.",
                         font=FONT_SMALL, text_color=("gray40", "gray70")).pack(padx=20, pady=40)


# =============================================================================
# TAB 3 — THÔNG TIN PHẦN MỀM & BẢN QUYỀN
# =============================================================================
class Tab3InfoFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")

        version_str = DEFAULT_VERSION
        # Đọc version.json từ đúng thư mục dữ liệu (được run_app.py truyền qua biến
        # môi trường TDM_APP_DATA_DIR) thay vì thư mục làm việc hiện tại (cwd), vì
        # cwd có thể khác nơi thực sự chứa file version.json vừa được cập nhật —
        # trước đây điều này khiến Tab này luôn hiển thị phiên bản cũ dù đã cập nhật.
        data_dir = os.environ.get("TDM_APP_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
        version_path = os.path.join(data_dir, "version.json")
        if os.path.exists(version_path):
            try:
                with open(version_path, "r", encoding="utf-8") as f:
                    v_data = json.load(f)
                    version_str = v_data.get("version", version_str)
            except Exception:
                pass

        ctk.CTkLabel(self, text="ℹ️ Thông tin phần mềm & Bản quyền", font=FONT_H1).pack(anchor="w", padx=6, pady=(6, 16))

        info_box = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray95", "gray14"))
        info_box.pack(fill="x", padx=6, pady=(0, 16))
        ctk.CTkLabel(info_box, text="💊 Phần mềm TDM Aminoglycosid", font=FONT_H2).pack(anchor="w", padx=16, pady=(14, 6))
        for line in [
            f"•  Phiên bản hiện tại: {version_str}",
            f"•  Bản quyền sở hữu và phát triển: {COPYRIGHT_EMAIL}",
            "•  Cơ sở dữ liệu: Supabase Cloud Database",
        ]:
            ctk.CTkLabel(info_box, text=line, font=FONT_NORMAL, anchor="w").pack(anchor="w", padx=16, pady=2)
        ctk.CTkLabel(info_box, text="", font=FONT_NORMAL).pack(pady=(0, 6))

        guide_box = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray95", "gray14"))
        guide_box.pack(fill="both", expand=True, padx=6)
        ctk.CTkLabel(guide_box, text="📖 Hướng dẫn sử dụng nhanh", font=FONT_H2).pack(anchor="w", padx=16, pady=(14, 6))

        guide_text = (
            "1. Tab Tính toán & TDM:\n"
            "   • Nhập thông tin hành chính bệnh nhân và thông số quần thể.\n"
            "   • Thực hiện tính toán cá thể hóa dựa trên 2 mức nồng độ máu (C1, C2).\n"
            "   • Hiệu chỉnh liều mới, xem trực quan biểu đồ nồng độ tích lũy qua nhiều\n"
            "     chu kỳ liều và lưu dữ liệu an toàn lên Cloud.\n\n"
            "2. Tab CSDL Bệnh nhân (Cloud):\n"
            "   • Tra cứu toàn bộ thông tin và lịch sử điều trị TDM của bệnh nhân theo\n"
            "     Mã số y tế (MSYT).\n"
            "   • Hỗ trợ xóa từng block TDM theo ngày hoặc xóa toàn bộ hồ sơ bệnh nhân\n"
            "     trên hệ thống đám mây khi cần thiết."
        )
        textbox = ctk.CTkTextbox(guide_box, height=260, font=FONT_NORMAL, wrap="word")
        textbox.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        textbox.insert("1.0", guide_text)
        textbox.configure(state="disabled")


# =============================================================================
# =============================================================================
# TAB 4 — TDM VANCOMYCIN (BAYES CÁ THỂ HÓA, MÔ HÌNH 2 NGĂN CÓ Vp)
# =============================================================================
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

    def open_calendar(self):
        current_dt = parse_vanco_datetime(self.dt_var.get())
        DateTimePickerWindow(self, initial_dt=current_dt, callback=lambda dt: self.dt_var.set(dt.strftime("%Y-%m-%d %H:%M")))

    def get_dose(self):
        dose_mg = parse_float(self.dose_var.get(), 0.0)
        given_at = parse_vanco_datetime(self.dt_var.get())
        return VancoDose(dose_mg=dose_mg, given_at=given_at)

    def get_tau(self):
        return parse_float(self.tau_var.get(), 12.0)


class Tab4VancoFrame(ctk.CTkScrollableFrame):
    """
    Tab TDM Vancomycin — ước lượng hậu nghiệm Bayes (CL, Vc, Vp) bằng mô hình dược động học 2 ngăn,
    tích hợp lịch chọn ngày giờ, thêm liều tự động và tính toán AUC mới.
    """

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.dose_rows = []
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

        # Khởi tạo sẵn 2 dòng liều mẫu
        now = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        self._add_dose_row(dose_default=1000.0, tau_default=12.0, dt_default=now)
        self._add_dose_row(dose_default=1000.0, tau_default=12.0, dt_default=now + datetime.timedelta(hours=12))

    def _section_header(self, text):
        ctk.CTkLabel(self, text=text, font=FONT_H2).pack(anchor="w", padx=6, pady=(18, 6))

    # ---------------------------------------------------------------
    def _build_patient_section(self):
        self._section_header("💉 TDM Vancomycin — Bayes cá thể hóa (mô hình 2 ngăn)")
        ctk.CTkLabel(
            self,
            text="Ước lượng hậu nghiệm CL, Vc, Vp bằng tối ưu hóa Bayes dựa trên tham số tiền nghiệm quần thể.",
            font=FONT_SMALL, text_color=("gray40", "gray70"), justify="left", wraplength=900,
        ).pack(anchor="w", padx=6, pady=(0, 10))

        self._section_header("1. Thông tin bệnh nhân")
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=6)
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1, uniform="vcol")

        c1 = ctk.CTkFrame(grid, fg_color="transparent")
        c1.grid(row=0, column=0, sticky="new", padx=(0, 10))
        self.v_msyt_entry = LabeledEntry(c1, "MSYT (Bắt buộc để lưu)")
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
        self.v_scr_entry = LabeledEntry(c2, "SCr (μmol/L hoặc mg/dL)", default=80.0)
        self.v_scr_entry.pack(fill="x")

        c3 = ctk.CTkFrame(grid, fg_color="transparent")
        c3.grid(row=0, column=2, sticky="new", padx=(10, 0))
        self.v_dialysis_check = LabeledCheck(c3, "Đang lọc máu (Hemodialysis)", default=False)
        self.v_dialysis_check.pack(fill="x", pady=(10, 4))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)

    # ---------------------------------------------------------------
    def _build_priors_section(self):
        self._section_header("2. Tham số tiền nghiệm (Priors cố định quần thể)")
        ctk.CTkLabel(
            self, text="Các thông số Q, Omega, Sai số chuẩn SD và CV được cố định theo chuẩn mô hình quần thể để tránh sai lệch.",
            font=FONT_SMALL, text_color=("gray40", "gray70"), justify="left"
        ).pack(anchor="w", padx=6, pady=(0, 6))

        # Hiển thị thông tin read-only thay cho ô nhập liệu có thể chỉnh sửa
        priors_info_frame = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=8)
        priors_info_frame.pack(fill="x", padx=6, pady=(4, 8))
        
        info_text = "• Q = 6.5 L/h (Cố định)\n• ωCL = 0.398  |  ωVc = 0.816  |  ωVp = 0.571\n• SD sai số dư = 0.34  |  CV sai số dư = 0.227 (22.7%)"
        ctk.CTkLabel(priors_info_frame, text=info_text, font=FONT_SMALL, justify="left", text_color=("gray25", "gray80")).pack(anchor="w", padx=12, pady=10)

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
            scr_value=self.v_scr_entry.get_float(80.0),
            is_dialysis=self.v_dialysis_check.get(),
        )

    def calc_priors(self):
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

    def _insert_dose_row(self, dose_default, tau_default, dt_default, index):
        row = VancoDoseRow(self.doses_container, on_remove=self._remove_dose_row, on_auto_add=self._auto_add_dose_row,
                            dose_default=dose_default, tau_default=tau_default, dt_default=dt_default)
        row.pack(fill="x", pady=3)
        self.dose_rows.insert(index, row)

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

    def _get_doses(self):
        doses = [r.get_dose() for r in self.dose_rows]
        doses.sort(key=lambda d: d.given_at)
        return doses

    # ---------------------------------------------------------------
    def _build_measurement_section(self):
        self._section_header("4. Nồng độ đo được (TDM)")
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=6)
        row.grid_columnconfigure((0, 1, 2), weight=1, uniform="ms")
        
        self.v_cobs_entry = LabeledEntry(row, "Cobs — Nồng độ đo được (μg/mL)", default=15.0)
        self.v_cobs_entry.grid(row=0, column=0, sticky="ew", padx=4)

        # Tobs với popup lịch chọn ngày giờ
        tobs_frame = ctk.CTkFrame(row, fg_color="transparent")
        tobs_frame.grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkLabel(tobs_frame, text="Tobs — Thời điểm lấy mẫu (YYYY-MM-DD HH:MM)", font=FONT_SMALL).pack(anchor="w")
        
        tobs_sub = ctk.CTkFrame(tobs_frame, fg_color="transparent")
        tobs_sub.pack(fill="x", pady=(2, 4))
        self.v_tobs_entry = ctk.CTkEntry(tobs_sub)
        self.v_tobs_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.v_tobs_entry.insert(0, datetime.datetime.now().replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M"))
        ctk.CTkButton(tobs_sub, text="📅", width=36, command=self.open_tobs_calendar).pack(side="left")

        self.v_tinf_entry = LabeledEntry(row, "Tinf — Thời gian truyền mỗi liều (h)", default=1.0)
        self.v_tinf_entry.grid(row=0, column=2, sticky="ew", padx=4)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)

    def open_tobs_calendar(self):
        current_dt = parse_vanco_datetime(self.v_tobs_entry.get())
        DateTimePickerWindow(self, initial_dt=current_dt, callback=lambda dt: self.v_tobs_entry.delete(0, 'end') or self.v_tobs_entry.insert(0, dt.strftime("%Y-%m-%d %H:%M")))

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

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)

    def run_bayes_solve(self):
        self.calc_priors()
        doses = self._get_doses()
        if not doses:
            self.solve_status.show("⚠️ Vui lòng nhập ít nhất 1 liều ở Mục 3.", "warning")
            return

        tobs = parse_vanco_datetime(self.v_tobs_entry.get())
        cobs = self.v_cobs_entry.get_float(0.0)
        tinf = self.v_tinf_entry.get_float(1.0)
        if cobs <= 0:
            self.solve_status.show("⚠️ Cobs phải lớn hơn 0.", "warning")
            return

        measurement = VancoMeasurement(c_obs=cobs, t_obs=tobs, t_inf_h=tinf)
        sd = 0.34
        cv = 0.227

        result = solve_bayesian_posterior(self.priors, doses, measurement, sd=sd, cv=cv)
        self.bayes_result = result
        self.measurement_used = measurement
        self.doses_used = doses

        if not result.success:
            self.solve_status.show(f"❌ {result.message}", "error")
            return

        self.solve_status.show(f"✅ {result.message}", "success")
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

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)

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
        q = 6.5
        times, concs = simulate_concentration_curve(
            r.CL_optimized, r.Vc_optimized, r.Vp_optimized, q,
            self.doses_used, self.measurement_used.t_inf_h,
            t_end=self.measurement_used.t_obs + datetime.timedelta(hours=6))

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
        ax.scatter([self.measurement_used.t_obs], [self.measurement_used.c_obs],
                   color="#d1242f", zorder=5, label=f"Cobs đo được ({self.measurement_used.c_obs:g} μg/mL)")
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

    def save_result(self):
        msyt_input = self.v_msyt_entry.get().strip()
        if not msyt_input:
            self.save_status.show("⚠️ Vui lòng nhập MSYT.", "error")
            return
        if self.bayes_result is None or not self.bayes_result.success:
            self.save_status.show("⚠️ Vui lòng chạy tối ưu Bayes trước khi lưu.", "warning")
            return

        patient = self._get_patient()
        r = self.bayes_result
        m = self.measurement_used
        date_str = m.t_obs.strftime("%Y-%m-%d")
        doses_payload = [{"dose_mg": d.dose_mg, "given_at": d.given_at.strftime("%Y-%m-%d %H:%M")}
                          for d in self.doses_used]

        ok, msg = db.save_vanco_tdm(
            msyt=msyt_input, tdm_date=date_str,
            age=patient.age, gender=patient.gender, height=patient.height_cm,
            weight=patient.weight_kg, scr=patient.scr_value, is_dialysis=int(patient.is_dialysis),
            q_prior=6.5,
            cl_prior=self.priors.cl_prior if self.priors else None,
            vc_prior=self.priors.vc_prior if self.priors else None,
            vp_prior=self.priors.vp_prior if self.priors else None,
            doses_json=doses_payload,
            c_obs=m.c_obs, t_obs=m.t_obs.strftime("%Y-%m-%d %H:%M"), t_inf=m.t_inf_h,
            cl_optimized=r.CL_optimized, vc_optimized=r.Vc_optimized, vp_optimized=r.Vp_optimized,
            c_pred_final=r.C_pred_final, ofv_final=r.OFV_final,
        )
        self.save_status.show(("✅ " if ok else "❌ ") + msg, "success" if ok else "error")


# =============================================================================
# GIAO DIỆN CHÍNH SAU KHI ĐĂNG NHẬP (Sidebar + Tabview)
# =============================================================================
class MainAppFrame(ctk.CTkFrame):
    def __init__(self, master, app, username, fullname, role):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.username, self.fullname, self.role = username, fullname, role

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content()

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=("gray90", "gray13"))
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text="👤 Thông tin tài khoản", font=FONT_H2).pack(anchor="w", padx=18, pady=(24, 12))
        ctk.CTkLabel(sidebar, text=f"Họ tên:\n{self.fullname}", font=FONT_SMALL, justify="left",
                     anchor="w").pack(anchor="w", padx=18, pady=4)
        ctk.CTkLabel(sidebar, text=f"Tài khoản: {self.username}", font=FONT_SMALL,
                     anchor="w").pack(anchor="w", padx=18, pady=4)
        ctk.CTkLabel(sidebar, text=f"Vai trò: {self.role}", font=FONT_SMALL,
                     anchor="w").pack(anchor="w", padx=18, pady=4)

        if self.role == "admin":
            badge = ctk.CTkLabel(sidebar, text="⚙️ Quyền Quản trị viên (Admin)", font=FONT_SMALL,
                                  fg_color="#0969da", text_color="white", corner_radius=6)
            badge.pack(anchor="w", padx=18, pady=(10, 4), ipadx=6, ipady=4)

        ctk.CTkButton(sidebar, text="🚪 Đăng xuất", fg_color="#d1242f", hover_color="#a01c24",
                      command=self.app.logout).pack(side="bottom", fill="x", padx=18, pady=24)

    def _build_content(self):
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew", padx=18, pady=14)
        content.grid_rowconfigure(1, weight=1)
        content.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(content, text="💊 Phần mềm TDM Aminoglycosid", font=FONT_H1).grid(
            row=0, column=0, sticky="w", pady=(0, 10))

        tabview = ctk.CTkTabview(content)
        tabview.grid(row=1, column=0, sticky="nsew")
        tab1 = tabview.add("🧮 Tính toán & TDM")
        tab2 = tabview.add("🗂 CSDL Bệnh nhân (Cloud)")
        tab3 = tabview.add("ℹ️ Thông tin phần mềm")
        tab4 = tabview.add("💉 TDM Vancomycin (Bayes)")

        for tab in (tab1, tab2, tab3, tab4):
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)

        Tab1CalcFrame(tab1, self.app).grid(row=0, column=0, sticky="nsew")
        Tab2DatabaseFrame(tab2, self.app).grid(row=0, column=0, sticky="nsew")
        Tab3InfoFrame(tab3, self.app).grid(row=0, column=0, sticky="nsew")
        Tab4VancoFrame(tab4, self.app).grid(row=0, column=0, sticky="nsew")


# =============================================================================
# ỨNG DỤNG CHÍNH
# =============================================================================
class TDMApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("💊 Phần mềm TDM Aminoglycosid")
        self.geometry("1280x820")
        self.minsize(1024, 680)

        db.init_db()

        self.current_frame = None
        self.show_login()

    def _clear(self):
        if self.current_frame is not None:
            self.current_frame.destroy()
            self.current_frame = None

    def show_login(self):
        self._clear()
        self.current_frame = LoginFrame(self, on_success=self.show_main)
        self.current_frame.pack(fill="both", expand=True)

    def show_main(self, username, fullname, role):
        self._clear()
        self.current_frame = MainAppFrame(self, self, username, fullname, role)
        self.current_frame.pack(fill="both", expand=True)

    def logout(self):
        self.show_login()


def main():
    """Điểm khởi chạy giao diện Windows (được gọi từ run_app.py)"""
    app = TDMApp()
    app.mainloop()


if __name__ == "__main__":
    main()

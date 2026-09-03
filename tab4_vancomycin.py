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
from vanco_calculations import (
    VancoPatientInfo, VancoDose, VancoMeasurement,
    compute_population_priors, solve_bayesian_posterior,
    simulate_concentration_curve,
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
        cols = ["Ngày TDM", "Cl_optimized", "Vc_optimized", "Vp_optimized", "AUC hiện tại"]
        self.prev_tree["columns"] = cols
        for col in cols:
            self.prev_tree.heading(col, text=col)
            self.prev_tree.column(col, width=130, anchor="center")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.prev_tree.yview)
        self.prev_tree.configure(yscrollcommand=vsb.set)
        self.prev_tree.pack(side="left", fill="x", expand=True)
        vsb.pack(side="right", fill="y")

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
        if record.get("scr") is not None:
            self.v_scr_entry.set(record.get("scr"))
        self.v_dialysis_check.set(bool(record.get("is_dialysis")))

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
        if not df_history.empty:
            for _, r in df_history.iterrows():
                d_date = str(r.get("tdm_date", ""))
                cl = f"{r.get('cl_optimized', 0):.4f}" if pd.notnull(r.get('cl_optimized')) else "--"
                vc = f"{r.get('vc_optimized', 0):.2f}" if pd.notnull(r.get('vc_optimized')) else "--"
                vp = f"{r.get('vp_optimized', 0):.2f}" if pd.notnull(r.get('vp_optimized')) else "--"
                auc = f"{r.get('auc_current', 0):.2f}" if pd.notnull(r.get('auc_current')) else "--"
                self.prev_tree.insert("", "end", values=(d_date, cl, vc, vp, auc))

            # Nạp Cobs/Tobs/Tinf của lần gần nhất (dòng đầu tiên) để tham khảo/chỉnh sửa
            latest = df_history.iloc[0]
            if pd.notnull(latest.get("c_obs")):
                self.v_cobs_entry.set(latest.get("c_obs"))
            if latest.get("t_obs"):
                self.v_tobs_entry.delete(0, "end")
                self.v_tobs_entry.insert(0, str(latest.get("t_obs")))
            if pd.notnull(latest.get("t_inf")):
                self.v_tinf_entry.set(latest.get("t_inf"))

        # Tính lại priors ngay theo dữ liệu vừa tải để các thẻ Mục 2 cập nhật theo
        self.calc_priors()

        self.v_lookup_status.show(f"✅ Đã tải dữ liệu bệnh nhân {msyt}.", "success")

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

        row3 = ctk.CTkFrame(self, fg_color="transparent")
        row3.pack(fill="x", padx=6, pady=(8, 0))
        ctk.CTkLabel(
            row3, text="AUC hiện tại = Liều × 24 / (τ × Clbn) — tính theo LIỀU CUỐI CÙNG ở Mục 3",
            font=FONT_SMALL, text_color=("gray40", "gray70")
        ).pack(anchor="w", pady=(0, 4))
        self.card_auc_current = MetricCard(row3, "AUC hiện tại (mg·h/L)")
        self.card_auc_current.pack(fill="x", padx=4, pady=4)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6, pady=14)

    def _get_last_dose_row(self):
        """Trả về VancoDoseRow có thời điểm truyền MUỘN NHẤT (liều cuối cùng ở Mục 3)."""
        if not self.dose_rows:
            return None
        return max(self.dose_rows, key=lambda r: r.get_dose().given_at)

    def calc_auc_current(self):
        """AUC hiện tại = Liều (của liều cuối cùng ở Mục 3) × 24 / (τ của liều đó × Clbn
        vừa tối ưu Bayes). Kết quả được lưu vào self.auc_current_value để dùng khi lưu Cloud."""
        if self.bayes_result is None or not self.bayes_result.success:
            self.card_auc_current.set_value("Chưa chạy solve Bayes")
            self.auc_current_value = None
            return None

        last_row = self._get_last_dose_row()
        if last_row is None:
            self.card_auc_current.set_value("Chưa có liều ở Mục 3")
            self.auc_current_value = None
            return None

        last_dose = last_row.get_dose()
        tau = last_row.get_tau()
        clbn = self.bayes_result.CL_optimized
        if tau <= 0 or clbn <= 0:
            self.card_auc_current.set_value("Giá trị không hợp lệ")
            self.auc_current_value = None
            return None

        auc = (last_dose.dose_mg * 24.0) / (tau * clbn)
        self.card_auc_current.set_value(f"{auc:.2f} mg·h/L")
        self.auc_current_value = auc
        return auc

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

        patient = self._get_patient()
        r = self.bayes_result
        m = self.measurement_used
        date_str = m.t_obs.strftime("%Y-%m-%d")
        doses_payload = [{"dose_mg": d.dose_mg, "given_at": d.given_at.strftime("%Y-%m-%d %H:%M")}
                          for d in self.doses_used]

        # Đảm bảo AUC hiện tại đã được tính theo dữ liệu mới nhất trước khi lưu
        auc_current = self.calc_auc_current()

        # --- 1) Thông tin bệnh nhân + chế độ liều dùng: CHỈ LƯU/GHI ĐÈ BẢN MỚI NHẤT ---
        ok1, msg1 = db.save_vanco_patient_current(
            msyt=msyt_input,
            age=patient.age, gender=patient.gender, height=patient.height_cm,
            weight=patient.weight_kg, scr=patient.scr_value, is_dialysis=int(patient.is_dialysis),
            doses_json=doses_payload,
        )

        # --- 2) Kết quả lần TDM này: LUÔN THÊM MỚI vào lịch sử, không ghi đè ---
        ok2, msg2 = db.save_vanco_result_history(
            msyt=msyt_input, tdm_date=date_str,
            q_prior=6.5,
            cl_prior=self.priors.cl_prior if self.priors else None,
            vc_prior=self.priors.vc_prior if self.priors else None,
            vp_prior=self.priors.vp_prior if self.priors else None,
            c_obs=m.c_obs, t_obs=m.t_obs.strftime("%Y-%m-%d %H:%M"), t_inf=m.t_inf_h,
            cl_optimized=r.CL_optimized, vc_optimized=r.Vc_optimized, vp_optimized=r.Vp_optimized,
            c_pred_final=r.C_pred_final, ofv_final=r.OFV_final,
            auc_current=auc_current,
        )

        if ok1 and ok2:
            self.save_status.show(
                "✅ Đã lưu bản mới nhất (thông tin BN + liều dùng) và thêm mới vào lịch sử kết quả TDM.",
                "success")
        else:
            combined = "; ".join([msg for ok, msg in [(ok1, msg1), (ok2, msg2)] if not ok])
            self.save_status.show(f"⚠️ Lưu chưa trọn vẹn: {combined}", "error")

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
    PatientInfo, DoseBlock,
    compute_bmi, compute_ibw, compute_dosing_weight, compute_initial_dose_sop,
    compute_predicted_cp_adjusted, compute_predicted_ctrough_adjusted,
    compute_block_individual, sop_check_blocks,
    parse_sz_datetime, format_sz_datetime, round_to_step, SOP_DOSE_RULES,
    DRUG_LIST, SEVERITY_LIST, SEVERITY_LIFE,
    simulate_dosing_curve,
)
from ui_common import (
    FONT_H2, FONT_SMALL,
    parse_date, today_str, clean_vn_text, parse_float,
    LabeledEntry, LabeledOption, LabeledCheck, MetricCard, StatusLabel,
)
from amg_bayesian_calculations import (
    AmgPatientInfo, AmgDose, AmgMeasurement,
    scr_to_mgdl, solve_bayesian_joint_amg, assign_measurements_amg,
    check_model_applicability_amg, compute_css_peak_trough_amg,
    simulate_concentration_curve_amg_tv,
    # v16.10.26 -- da mo hinh
    AmgClinicalInfo, AMG_MODELS, models_for_drug, model_key_from_label, recommend_model_amg,
    solve_bayesian_multi, check_model_applicability_multi, compute_css_peak_trough_multi,
    simulate_concentration_curve_multi, fit_diagnostics_amg, check_dose_overlap_amg,
    get_lloq_amg, check_below_lloq_amg,
)

AMG_SETTING_LABELS = {"": "— chưa chọn —", "icu": "Hồi sức tích cực (ICU)", "ward": "Nội trú ngoài hồi sức"}
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
def parse_amg_dt_strict(value):
    """Như parse_amg_dt nhưng KHÔNG tự thay bằng giờ hiện tại khi sai định dạng: trả về None."""
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except Exception:
            continue
    return None
class AmgDoseRow(ctk.CTkFrame):
    """Một liều: Liều thứ n — thời gian bắt đầu — liều (mg) — thời gian truyền Tinf (h).
    τ (h) là khoảng đưa liều, CHỈ dùng cho nút '➕ Tự động' (tự thêm liều kế tiếp) và cho Cpeak/Ctrough hiện tại."""
    def __init__(self, master, on_remove, on_auto_add, dose_default=400.0, tau_default=24.0,
                 dt_default=None, tinf_default=1.0, **kwargs):
        super().__init__(master, fg_color=("gray95", "gray16"), corner_radius=6, **kwargs)
        dt_default = dt_default or datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        self.on_auto_add_callback = on_auto_add
        self.dose_var = ctk.StringVar(value=f"{dose_default:g}")
        self.tau_var = ctk.StringVar(value=f"{tau_default:g}")
        self.tinf_var = ctk.StringVar(value=f"{tinf_default:g}")
        self.dt_var = ctk.StringVar(value=dt_default.strftime("%Y-%m-%d %H:%M"))
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=8, pady=6)
        self.seq_label = ctk.CTkLabel(grid, text="Liều thứ 1:", font=FONT_SMALL, width=70, anchor="w")
        self.seq_label.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(grid, text="Bắt đầu:", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(grid, textvariable=self.dt_var, width=130).pack(side="left", padx=(0, 4))
        ctk.CTkButton(grid, text="📅", width=32, command=self.open_calendar).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(grid, text="Liều (mg):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(grid, textvariable=self.dose_var, width=65).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(grid, text="Tinf (h):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(grid, textvariable=self.tinf_var, width=45).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(grid, text="τ (h):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(grid, textvariable=self.tau_var, width=45).pack(side="left", padx=(0, 8))
        ctk.CTkButton(grid, text="➕ Tự động", width=75, fg_color="#1f6feb", hover_color="#1158c7",
                      command=lambda: self.on_auto_add_callback(self)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(grid, text="🗑", width=32, fg_color="#d1242f", hover_color="#a01c24",
                      command=lambda: on_remove(self)).pack(side="left")
    def set_seq(self, num):
        self.seq_label.configure(text=f"Liều thứ {num}:")
    def open_calendar(self):
        AmgDateTimePickerWindow(self, initial_dt=parse_amg_dt(self.dt_var.get()),
                                 callback=lambda dt: self.dt_var.set(dt.strftime("%Y-%m-%d %H:%M")))
    def get_dose(self):
        """Trả về AmgDose; dữ liệu sai -> ValueError (KHÔNG tự thay bằng giờ hiện tại)."""
        t0 = parse_amg_dt_strict(self.dt_var.get())
        if t0 is None:
            raise ValueError("thời điểm bắt đầu sai định dạng (YYYY-MM-DD HH:MM)")
        dose = _to_float(self.dose_var.get())
        if dose is None or dose <= 0:
            raise ValueError("liều (mg) phải là số > 0")
        tinf = _to_float(self.tinf_var.get())
        if tinf is None or tinf <= 0:
            raise ValueError("thời gian truyền Tinf (h) phải là số > 0")
        return AmgDose(dose_mg=dose, given_at=t0, t_inf_h=tinf)
    def try_dose(self):
        try:
            return self.get_dose()
        except ValueError:
            return None
    def get_tau(self):
        v = _to_float(self.tau_var.get())
        return v if v and v > 0 else 24.0
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
    def get_raw(self):
        """(giá trị SCr GỐC người dùng nhập, đơn vị đã chọn, thời điểm đo) — dùng khi lưu/tải lại.
        Dữ liệu sai -> ValueError."""
        t0 = parse_amg_dt_strict(self.dt_var.get())
        if t0 is None:
            raise ValueError("thời điểm đo sai định dạng (YYYY-MM-DD HH:MM)")
        raw = _to_float(self.scr_var.get())
        if raw is None or raw <= 0:
            raise ValueError("giá trị SCr phải là số > 0")
        return raw, self.unit_var.get(), t0
    def get_scr(self):
        """(SCr đã quy đổi mg/dL, thời điểm đo). Quy đổi theo đơn vị người dùng chọn, ĐÚNG 1 LẦN tại đây
        (scr_to_mgdl) — mọi hàm tính toán phía sau nhận SCr đã là mg/dL, không quy đổi lại."""
        raw, unit, t0 = self.get_raw()
        return scr_to_mgdl(raw, unit), t0
class AmgMeasRow(ctk.CTkFrame):
    """Một điểm đo: Cobs + Tobs. Phần mềm TỰ xác định mẫu thuộc liều thứ mấy (nhãn bên phải, cập nhật
    sau khi chạy). Thời gian truyền lấy từ liều tương ứng trong bảng liều."""
    def __init__(self, master, on_remove, cobs_default=8.0, dt_default=None, **kwargs):
        super().__init__(master, fg_color=("gray95", "gray16"), corner_radius=6, **kwargs)
        dt_default = dt_default or datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        self.cobs_var = ctk.StringVar(value=str(cobs_default))
        self.dt_var = ctk.StringVar(value=dt_default.strftime("%Y-%m-%d %H:%M"))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=6)
        ctk.CTkLabel(row, text="Cobs (μg/mL):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.cobs_var, width=65).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text="Tobs:", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=self.dt_var, width=130).pack(side="left", padx=(0, 4))
        ctk.CTkButton(row, text="📅", width=32, command=self.open_calendar).pack(side="left", padx=(0, 6))
        ctk.CTkButton(row, text="🗑", width=32, fg_color="#d1242f", hover_color="#a01c24",
                      command=lambda: on_remove(self)).pack(side="left", padx=(0, 8))
        self.assign_label = ctk.CTkLabel(row, text="", font=FONT_SMALL, text_color=("gray40", "gray70"))
        self.assign_label.pack(side="left")
    def open_calendar(self):
        AmgDateTimePickerWindow(self, initial_dt=parse_amg_dt(self.dt_var.get()),
                                 callback=lambda dt: self.dt_var.set(dt.strftime("%Y-%m-%d %H:%M")))
    def set_assignment(self, text, warn=False):
        self.assign_label.configure(text=text, text_color=("#9a6700", "#d29922") if warn else ("gray40", "gray70"))
    def get_measurement(self):
        t0 = parse_amg_dt_strict(self.dt_var.get())
        if t0 is None:
            raise ValueError("Tobs sai định dạng (YYYY-MM-DD HH:MM)")
        c = _to_float(self.cobs_var.get())
        if c is None or c <= 0:
            raise ValueError("Cobs phải là số > 0")
        return AmgMeasurement(c_obs=c, t_obs=t0)
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
def _to_float(text):
    """Đọc số (chấp nhận dấu phẩy thập phân). Rỗng/sai -> None."""
    try:
        s = str(text).strip().replace(",", ".")
        return float(s) if s != "" else None
    except ValueError:
        return None
class SzDoseBlock(ctk.CTkFrame):
    """Một liều THỰC TẾ + 2 dòng thời điểm định lượng (Sawchuk–Zaske nhiều liều):
         Liều thứ n:  dd/mm/yyyy hh:mm | SCr | Tổng liều thực tế | τ | Tinf
             Thời điểm định lượng 1: dd/mm/yyyy hh:mm   Nồng độ AG:
             Thời điểm định lượng 2: dd/mm/yyyy hh:mm   Nồng độ AG:
    Liều không lấy mẫu vẫn nhập (để cộng dồn tồn dư khi tính các liều sau)."""
    def __init__(self, master, on_remove, start_default=None, scr_default=80.0, dose_default=400.0,
                 tau_default=24.0, tinf_default=1.0, **kwargs):
        super().__init__(master, fg_color=("gray95", "gray16"), corner_radius=8, **kwargs)
        start_default = start_default or datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        self.start_var = ctk.StringVar(value=format_sz_datetime(start_default))
        self.scr_var = ctk.StringVar(value=f"{scr_default:g}" if scr_default is not None else "")
        self.dose_var = ctk.StringVar(value=f"{dose_default:g}")
        self.tau_var = ctk.StringVar(value=f"{tau_default:g}")
        self.tinf_var = ctk.StringVar(value=f"{tinf_default:g}")
        self.s1_var, self.c1_var = ctk.StringVar(value=""), ctk.StringVar(value="")
        self.s2_var, self.c2_var = ctk.StringVar(value=""), ctk.StringVar(value="")
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=8, pady=(8, 2))
        self.seq_label = ctk.CTkLabel(head, text="Liều thứ 1:", font=("Arial", 12, "bold"), width=80, anchor="w")
        self.seq_label.pack(side="left", padx=(0, 6))
        ctk.CTkEntry(head, textvariable=self.start_var, width=135).pack(side="left", padx=(0, 4))
        ctk.CTkButton(head, text="📅", width=32, command=lambda: self._pick(self.start_var)).pack(side="left", padx=(0, 10))
        for text, var, w in (("SCr (μmol/L):", self.scr_var, 55), ("Tổng liều thực tế (mg):", self.dose_var, 65),
                             ("τ (h):", self.tau_var, 45), ("Tinf (h):", self.tinf_var, 45)):
            ctk.CTkLabel(head, text=text, font=FONT_SMALL).pack(side="left", padx=(0, 2))
            ctk.CTkEntry(head, textvariable=var, width=w).pack(side="left", padx=(0, 8))
        ctk.CTkButton(head, text="🗑", width=32, fg_color="#d1242f", hover_color="#a01c24",
                      command=lambda: on_remove(self)).pack(side="left")
        self.t1_label = self._sample_row("Thời điểm định lượng 1:", self.s1_var, self.c1_var)
        self.t2_label = self._sample_row("Thời điểm định lượng 2:", self.s2_var, self.c2_var)
        self.result_label = ctk.CTkLabel(self, text="", font=FONT_SMALL, anchor="w", justify="left", wraplength=980)
        self.result_label.pack(fill="x", padx=(40, 8), pady=(0, 6))
        for v in (self.start_var, self.s1_var, self.s2_var):
            v.trace_add("write", lambda *a: self._refresh_hours())
        self._refresh_hours()
    def _sample_row(self, title, tvar, cvar):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=(40, 8), pady=1)
        ctk.CTkLabel(row, text=title, font=FONT_SMALL, width=150, anchor="w").pack(side="left", padx=(0, 4))
        ctk.CTkEntry(row, textvariable=tvar, width=135).pack(side="left", padx=(0, 4))
        ctk.CTkButton(row, text="📅", width=32, command=lambda: self._pick(tvar)).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text="Nồng độ AG (μg/mL):", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        ctk.CTkEntry(row, textvariable=cvar, width=70).pack(side="left", padx=(0, 10))
        lbl = ctk.CTkLabel(row, text="", font=FONT_SMALL, text_color=("gray40", "gray70"))
        lbl.pack(side="left")
        return lbl
    def _pick(self, var):
        AmgDateTimePickerWindow(self, initial_dt=parse_sz_datetime(var.get()),
                                 callback=lambda dt: var.set(format_sz_datetime(dt)))
    def _refresh_hours(self):
        start = parse_sz_datetime(self.start_var.get())
        for var, lbl, name in ((self.s1_var, getattr(self, "t1_label", None), "T1"),
                               (self.s2_var, getattr(self, "t2_label", None), "T2")):
            if lbl is None:
                continue
            t = parse_sz_datetime(var.get())
            lbl.configure(text=(f"{name} = {(t - start).total_seconds() / 3600.0:.2f} h kể từ lúc bắt đầu truyền"
                                if (t and start) else ""))
    def set_seq(self, n):
        self.seq_label.configure(text=f"Liều thứ {n}:")
    def set_result(self, lines):
        """lines: list (mức, nội dung) — hiển thị dưới khối, màu theo mức nặng nhất."""
        order = {"error": 2, "warn": 1, "info": 0}
        icon = {"error": "⛔", "warn": "⚠️", "info": "ℹ️"}
        if not lines:
            self.result_label.configure(text="")
            return
        worst = max((lv for lv, _ in lines), key=lambda x: order[x])
        color = {"error": "#d1242f", "warn": "#bf8700", "info": ("#1a7f37", "#3fb950")}[worst]
        self.result_label.configure(text="\n".join(f"{icon[lv]} {tx}" for lv, tx in lines), text_color=color)
    def get_block(self):
        """Trả về (DoseBlock hoặc None, [lỗi nhập liệu]). Thời điểm sai định dạng -> báo lỗi, không tự đoán."""
        issues = []
        start = parse_sz_datetime(self.start_var.get())
        if start is None:
            issues.append("thời điểm bắt đầu truyền sai định dạng (dd/mm/yyyy hh:mm)")
        s1, s2 = parse_sz_datetime(self.s1_var.get()), parse_sz_datetime(self.s2_var.get())
        if self.s1_var.get().strip() and s1 is None:
            issues.append("thời điểm định lượng 1 sai định dạng")
        if self.s2_var.get().strip() and s2 is None:
            issues.append("thời điểm định lượng 2 sai định dạng")
        dose, tau, tinf = _to_float(self.dose_var.get()), _to_float(self.tau_var.get()), _to_float(self.tinf_var.get())
        if dose is None or tau is None or tinf is None:
            issues.append("liều thực tế/τ/Tinf chưa nhập hoặc không phải số")
        if issues:
            return None, issues
        return DoseBlock(start=start, dose_mg=dose, tau_h=tau, t_inf_h=tinf, scr_umol=_to_float(self.scr_var.get()),
                         s1_time=s1, s1_conc=_to_float(self.c1_var.get()),
                         s2_time=s2, s2_conc=_to_float(self.c2_var.get())), []
    def load_from_dict(self, d):
        self.start_var.set(format_sz_datetime(parse_sz_datetime(d.get("start")) or datetime.datetime.now()))
        self.scr_var.set("" if d.get("scr_umol") is None else f"{d['scr_umol']:g}")
        self.dose_var.set(f"{d.get('dose_mg', 0):g}")
        self.tau_var.set(f"{d.get('tau_h', 24):g}")
        self.tinf_var.set(f"{d.get('t_inf_h', 1):g}")
        for tv, cv, kt, kc in ((self.s1_var, self.c1_var, "s1_time", "s1_conc"), (self.s2_var, self.c2_var, "s2_time", "s2_conc")):
            t = parse_sz_datetime(d.get(kt))
            tv.set(format_sz_datetime(t) if t else "")
            cv.set("" if d.get(kc) is None else f"{d[kc]:g}")
    def to_dict(self):
        b, _ = self.get_block()
        if b is None:
            return None
        iso = lambda t: t.strftime("%Y-%m-%d %H:%M") if t else None
        return {"start": iso(b.start), "scr_umol": b.scr_umol, "dose_mg": b.dose_mg, "tau_h": b.tau_h, "t_inf_h": b.t_inf_h,
                "s1_time": iso(b.s1_time), "s1_conc": b.s1_conc, "s2_time": iso(b.s2_time), "s2_conc": b.s2_conc}
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
        self.recalc_population()   # cần trước Mục 3 để dòng liều đầu lấy sẵn tổng liều đầu
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
        # v16.10.26d: dữ liệu Bayesian nằm ở bảng riêng (amg_bayesian_patient_current) — tra cứu cả hai nơi
        b_rec = db.get_amg_bayesian_patient_current(msyt)
        if self.amg_method_var.get() == "Bayesian" and b_rec:
            self.msyt_entry.set(msyt)
            self.load_amg_bayesian()
            self.lookup_status.show(f"✅ Đã tải dữ liệu Bayesian của bệnh nhân {msyt} (xem Mục G).", "success")
            return
        if p_data:
            self.loaded_patient = p_data
            self.loaded_tdm = t_data
            note = (" Bệnh nhân còn có dữ liệu Bayesian — chọn phương pháp Bayesian rồi tra cứu lại để xem."
                    if b_rec else "")
            self.lookup_status.show(f"✅ Đã tải thành công bệnh nhân: {msyt}.{note}", "success")
            self._apply_loaded_defaults(msyt)
        elif b_rec:
            # Chỉ có dữ liệu Bayesian (chưa từng tính Sawchuk–Zaske) → chuyển sang Bayesian và tải
            self.amg_method_var.set("Bayesian")
            self.on_amg_method_change()
            self.msyt_entry.set(msyt)
            self.load_amg_bayesian()
            self.lookup_status.show(f"✅ Bệnh nhân {msyt} chỉ có dữ liệu Bayesian — đã chuyển sang phương pháp Bayesian "
                                    "và tải dữ liệu.", "success")
        else:
            self.loaded_patient = None
            self.loaded_tdm = None
            self.lookup_status.show("❌ Không tìm thấy MSYT trong Cloud CSDL.", "error")
    def _parse_sz_json(self, raw):
        """sz_json từ Supabase có thể là dict (jsonb) hoặc chuỗi JSON."""
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                return None
        return raw if isinstance(raw, dict) else None
    def _apply_loaded_defaults(self, lookup_msyt):
        p = self.loaded_patient or {}
        t = self.loaded_tdm or {}
        sz = self._parse_sz_json(t.get("sz_json"))
        default_weight = float(p.get("weight", 70.0) or 70.0)
        default_height = float(p.get("height", 170.0) or 170.0)
        default_age = float(p.get("age", 50.0) or 50.0)
        self.msyt_entry.set(p.get("msyt", lookup_msyt))
        self.gender_opt.set(p.get("gender", "nam") if p.get("gender") in ("nam", "nữ") else "nam")
        self.weight_entry.set(default_weight)
        self.height_entry.set(default_height)
        self.age_entry.set(default_age)
        if sz:  # bản ghi mới: khôi phục đầy đủ Mục 1-3
            if sz.get("drug") in DRUG_LIST:
                self.drug_opt.set(sz["drug"])
            if sz.get("severity") in SEVERITY_LIST:
                self.severity_opt.set(sz["severity"])
            self.dose_mg_kg_entry.set(sz.get("dose_mg_kg", 5.0))
            self.target_cp_entry.set(sz.get("target_cp", 20.0))
            self.target_ctr_entry.set(sz.get("target_ctr", 1.0))
            self._clear_sz_blocks()
            for d in sz.get("blocks", []):
                self._add_sz_block(from_dict=d)
        else:   # bản ghi cũ (1 cặp T1/T2, không lưu liều/giờ thực tế): chỉ khôi phục thông tin chung
            default_dose_mg_kg = 5.0
            if t.get("new_dose") and default_weight > 0:
                default_dose_mg_kg = round(float(t.get("new_dose")) / default_weight, 2)
            self.dose_mg_kg_entry.set(default_dose_mg_kg)
            self.target_cp_entry.set(float(t.get("pred_cp", 20.0) or 20.0))
            self.target_ctr_entry.set(float(t.get("pred_ctrough", 1.0) or 1.0))
        self.recalc_population()
    # ---------------------------------------------------------------
    def _build_section1_patient(self):
        self._section_header("1. Thông tin bệnh nhân")
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=6)
        grid.grid_columnconfigure((0, 1), weight=1, uniform="col")
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
        # Tuổi: BẮT BUỘC cho Cockcroft–Gault (CrCl -> gợi ý T1/T2) và tiền nghiệm Bayesian
        self.age_entry = LabeledEntry(c1, "Tuổi", default=50.0)
        self.age_entry.pack(fill="x")
        c2 = ctk.CTkFrame(grid, fg_color="transparent")
        c2.grid(row=0, column=1, sticky="new", padx=(10, 0))
        self.drug_opt = LabeledOption(c2, "Aminoglycosid", DRUG_LIST, default=DRUG_LIST[0])
        self.drug_opt.pack(fill="x")
        self.severity_opt = LabeledOption(c2, "Mức độ nhiễm khuẩn", SEVERITY_LIST, default=SEVERITY_LIST[0])
        self.severity_opt.pack(fill="x")
        self.target_cp_entry = LabeledEntry(c2, "Cp kỳ vọng (μg/mL)", default=20.0)
        self.target_cp_entry.pack(fill="x")
        self.target_ctr_entry = LabeledEntry(c2, "Ctr kỳ vọng (μg/mL)", default=1.0)
        self.target_ctr_entry.pack(fill="x")
        # Tự động cập nhật Mục 2 (thông số quần thể) khi các trường liên quan thay đổi
        for widget in (self.weight_entry, self.height_entry, self.age_entry):
            widget.var.trace_add("write", lambda *a: self.recalc_population())
        for widget in (self.gender_opt, self.drug_opt, self.severity_opt):
            widget.var.trace_add("write", lambda *a: self.recalc_population())
        self.drug_opt.var.trace_add("write", lambda *a: self._update_amg_drug_note())
    # ---------------------------------------------------------------
    def _build_section2_population(self):
        self._section_header("2. Thông số quần thể tham khảo", parent=self.sz_container)
        row = ctk.CTkFrame(self.sz_container, fg_color="transparent")
        row.pack(fill="x", padx=6)
        row.grid_columnconfigure((0, 1, 2), weight=1, uniform="m")
        self.card_bmi = MetricCard(row, "BMI")
        self.card_bmi.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.card_ibw = MetricCard(row, "IBW (kg)")
        self.card_ibw.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.card_dosing_w = MetricCard(row, "Cân nặng tính liều (kg)")
        self.card_dosing_w.grid(row=0, column=2, sticky="ew", padx=4, pady=4)
        row2 = ctk.CTkFrame(self.sz_container, fg_color="transparent")
        row2.pack(fill="x", padx=6, pady=(4, 0))
        row2.grid_columnconfigure((0, 1), weight=1, uniform="m2")
        self.dose_mg_kg_entry = LabeledEntry(row2, "Liều khởi đầu (mg/kg) — người dùng nhập", default=5.0)
        self.dose_mg_kg_entry.grid(row=0, column=0, sticky="ew", padx=4)
        self.card_total_dose = MetricCard(row2, "Tổng liều đầu (đã giới hạn + làm tròn, mg)")
        self.card_total_dose.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.dose_mg_kg_entry.var.trace_add("write", lambda *a: self.recalc_population())
        self.dose_note_label = ctk.CTkLabel(self.sz_container, text="", font=FONT_SMALL, anchor="w", justify="left",
                                            wraplength=1000)
        self.dose_note_label.pack(fill="x", padx=10)
        ttk.Separator(self.sz_container, orient="horizontal").pack(fill="x", padx=6, pady=14)
    def _get_patient_info(self):
        return PatientInfo(
            gender=self.gender_opt.get(),
            height_cm=self.height_entry.get_float(170.0),
            weight_kg=self.weight_entry.get_float(70.0),
            scr_umol=100.0,   # SCr thực dùng cho từng liều nằm ở Mục 3
            age=self.age_entry.get_float(50.0),
            is_cf=False,
        )
    def recalc_population(self):
        if not hasattr(self, "card_total_dose") or not hasattr(self, "dose_note_label"):
            return
        patient = self._get_patient_info()
        life = self.severity_opt.get() == SEVERITY_LIFE
        bmi = compute_bmi(patient)
        ibw = compute_ibw(patient)
        dosing_weight = compute_dosing_weight(patient, ibw, life_threatening=life)
        mgkg = self.dose_mg_kg_entry.get_float(5.0)
        dose_info = compute_initial_dose_sop(mgkg, dosing_weight, self.drug_opt.get(), life)
        total_dose = dose_info["final"]
        self.card_bmi.set_value(f"{bmi:.2f}")
        self.card_ibw.set_value(f"{ibw:.2f}")
        self.card_dosing_w.set_value(f"{dosing_weight:.2f}")
        self.card_total_dose.set_value(f"{total_dose:g}")
        rule = ("nhiễm khuẩn đe dọa tính mạng: BMI ≤ 30 dùng cân nặng thực, BMI > 30 dùng AdjBW"
                if life else "theo quy trình: < IBW dùng cân nặng thực, ≤ 130% IBW dùng IBW, > 130% dùng AdjBW")
        note = f"Cân nặng tính liều {dosing_weight:.1f} kg ({rule})."
        note += f"\nTính được {dose_info['raw']:.1f} mg"
        if dose_info["was_capped"]:
            note += f" → vượt mức tối đa {dose_info['cap']:g} mg của quy trình, đã giới hạn"
        note += f" → làm tròn bội số {dose_info['step']:g} mg = {total_dose:g} mg."
        rng = f"{dose_info['mgkg_min']:g}–{dose_info['mgkg_max']:g} mg/kg"
        color = ("gray30", "gray70")
        if dose_info["mgkg_status"] == "high":
            note += (f"\n⛔ Liều {mgkg:g} mg/kg VƯỢT mức tối đa {dose_info['mgkg_max']:g} mg/kg của quy trình "
                     f"(khoảng khuyến cáo cho {self.drug_opt.get()}, {self.severity_opt.get().lower()}: {rng}). Hãy kiểm tra lại liều.")
            color = "#d1242f"
        elif dose_info["mgkg_status"] == "low":
            note += (f"\n⚠️ Liều {mgkg:g} mg/kg THẤP hơn khoảng khuyến cáo {rng} "
                     f"({self.drug_opt.get()}, {self.severity_opt.get().lower()}).")
            color = "#bf8700"
        else:
            note += f"\nℹ️ Liều {mgkg:g} mg/kg nằm trong khoảng khuyến cáo {rng}."
        if dose_info["was_capped"] and color != "#d1242f":
            color = "#bf8700"
        self.dose_note_label.configure(text=note, text_color=color)
        self._bmi, self._ibw, self._dosing_weight, self._total_dose = bmi, ibw, dosing_weight, total_dose
    # ---------------------------------------------------------------
    def _build_section3_individual(self):
        self._section_header("3. Cá thể hoá theo kết quả TDM (nhiều liều)", parent=self.sz_container)
        ctk.CTkLabel(
            self.sz_container, justify="left", anchor="w", font=FONT_SMALL, wraplength=1000,
            text_color=("gray35", "gray70"),
            text=("Nhập LẦN LƯỢT từng liều thực tế (kể cả liều không lấy máu). Với liều có lấy máu, nhập thêm 2 thời điểm định lượng "
                  "+ nồng độ. Phần mềm tự xác định đó là liều thứ mấy và tự cộng dồn tồn dư các liều trước; T1/T2 tự tính "
                  "từ ngày giờ (giờ kể từ lúc BẮT ĐẦU truyền). Mục 4 dùng kết quả của liều mới nhất có đủ 2 mẫu.")
        ).pack(fill="x", padx=10, pady=(0, 6))
        self.sz_blocks = []
        self.sz_blocks_container = ctk.CTkFrame(self.sz_container, fg_color="transparent")
        self.sz_blocks_container.pack(fill="x", padx=6)
        btn_row = ctk.CTkFrame(self.sz_container, fg_color="transparent")
        btn_row.pack(fill="x", padx=6, pady=(6, 0))
        ctk.CTkButton(btn_row, text="➕ Thêm liều kế tiếp", width=170, command=self._add_sz_block).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="🔎 Kiểm tra T1/T2 theo SOP", width=210, fg_color="#6e7781", hover_color="#57606a",
                      command=self.check_sz_sampling).pack(side="left")
        self.sampling_check_label = ctk.CTkLabel(self.sz_container, text="", font=FONT_SMALL, anchor="w",
                                                 justify="left", wraplength=1000)
        self.sampling_check_label.pack(fill="x", padx=10, pady=(4, 0))
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
        self.sec3_which_label = ctk.CTkLabel(self.sz_container, text="", font=FONT_SMALL, anchor="w",
                                             text_color=("gray35", "gray70"))
        self.sec3_which_label.pack(fill="x", padx=10)
        ctk.CTkButton(self.sz_container, text="💾 Xác nhận & Lưu lên Cloud (Mục 3)", height=36,
                      fg_color="#2f6f4f", hover_color="#254f39",
                      command=self.save_section3).pack(fill="x", padx=6, pady=(12, 4))
        self.save3_status = StatusLabel(self.sz_container)
        self.save3_status.pack(fill="x", padx=6)
        ttk.Separator(self.sz_container, orient="horizontal").pack(fill="x", padx=6, pady=14)
        self._add_sz_block()
    # --- quản lý các khối liều ---
    def _clear_sz_blocks(self):
        for b in self.sz_blocks:
            b.destroy()
        self.sz_blocks = []
    def _add_sz_block(self, from_dict=None):
        if from_dict is None:
            if self.sz_blocks:
                prev, _ = self.sz_blocks[-1].get_block()
                if prev is not None:
                    kw = dict(start_default=prev.start + datetime.timedelta(hours=prev.tau_h),
                              scr_default=prev.scr_umol if prev.scr_umol is not None else 80.0,
                              dose_default=prev.dose_mg, tau_default=prev.tau_h, tinf_default=prev.t_inf_h)
                else:
                    kw = {}
            else:
                kw = dict(dose_default=float(getattr(self, "_total_dose", 400.0) or 400.0))
            blk = SzDoseBlock(self.sz_blocks_container, on_remove=self._remove_sz_block, **kw)
        else:
            blk = SzDoseBlock(self.sz_blocks_container, on_remove=self._remove_sz_block)
            blk.load_from_dict(from_dict)
        blk.pack(fill="x", pady=4)
        self.sz_blocks.append(blk)
        self._renumber_sz_blocks()
    def _remove_sz_block(self, blk):
        if blk in self.sz_blocks:
            self.sz_blocks.remove(blk)
        blk.destroy()
        self._renumber_sz_blocks()
    def _renumber_sz_blocks(self):
        for i, b in enumerate(self.sz_blocks):
            b.set_seq(i + 1)
    def _collect_sz_blocks(self):
        """Sắp xếp các khối theo thời gian bắt đầu, đánh số lại, trả về (list[(frame, DoseBlock)], lỗi hoặc None)."""
        parsed = []
        for i, frame in enumerate(self.sz_blocks):
            blk, issues = frame.get_block()
            if blk is None:
                return None, f"Liều ở dòng {i + 1}: " + "; ".join(issues) + "."
            parsed.append((frame, blk))
        parsed.sort(key=lambda fb: fb[1].start)
        self.sz_blocks = [f for f, _ in parsed]
        for f in self.sz_blocks:
            f.pack_forget()
        for f in self.sz_blocks:
            f.pack(fill="x", pady=4)
        self._renumber_sz_blocks()
        return parsed, None
    def check_sz_sampling(self):
        """Nút kiểm tra T1/T2 theo SOP — CHỈ khuyến cáo, không chặn việc tính toán cá thể hóa."""
        parsed, err = self._collect_sz_blocks()
        if err:
            self.sampling_check_label.configure(text="⛔ " + err, text_color="#d1242f")
            return
        if not parsed:
            self.sampling_check_label.configure(text="Chưa có liều nào.", text_color="gray")
            return
        items = sop_check_blocks([b for _, b in parsed], self._get_patient_info())
        icon = {"error": "⛔", "warn": "⚠️", "info": "ℹ️"}
        lines, order, worst = [], {"error": 2, "warn": 1, "info": 0}, "info"
        for it in items:
            for lv, tx in it["lines"]:
                lines.append(f"{icon[lv]} {tx}")
                if order[lv] > order[worst]:
                    worst = lv
        lines.append("→ Đây chỉ là khuyến cáo: nếu vẫn dùng 2 thời điểm đã nhập, bỏ qua cảnh báo và nhấn «TÍNH TOÁN CÁ THỂ HÓA».")
        color = {"error": "#d1242f", "warn": "#bf8700", "info": "#2f6f4f"}[worst]
        self.sampling_check_label.configure(text="\n".join(lines), text_color=color)
    def calc_section3(self):
        parsed, err = self._collect_sz_blocks()
        if err:
            self.sec3_status.show("⛔ " + err, "error")
            self.sec3["calculated"] = False
            return
        blocks = [b for _, b in parsed]
        results = {}
        for i, (frame, b) in enumerate(parsed):
            if not b.has_any_sample():
                frame.set_result([])
                continue
            if not b.has_pair():
                frame.set_result([("warn", "Chưa đủ 2 mẫu (thời điểm + nồng độ > 0) — liều này chỉ dùng để cộng dồn, không tính cá thể hóa.")])
                continue
            res = compute_block_individual(blocks, i)
            results[i] = res
            lines = list(res["messages"])
            if res["ok"]:
                lines.insert(0, ("info", f"Liều thứ {i + 1}: Ke = {res['ke']:.4f} h⁻¹, t½ = {res['t_half']:.2f} h, Vd = {res['vd']:.2f} L, "
                                         f"Cp thật = {res['cp']:.2f}, Ctr thật = {res['ctr']:.3f} μg/mL"))
            frame.set_result(lines)
        ok_idx = [i for i, r in results.items() if r["ok"]]
        if not ok_idx:
            self.sec3["calculated"] = False
            self.sec3_status.show("❌ Chưa có liều nào đủ dữ liệu hợp lệ để tính — xem thông báo dưới từng liều.", "error")
            return
        k = max(ok_idx)
        r, b = results[k], blocks[k]
        self.sec3 = {"ke": r["ke"], "thalf": r["t_half"], "vd": r["vd"], "cp": r["cp"], "ctr": r["ctr"], "calculated": True,
                     "t_inf": b.t_inf_h, "tau": b.tau_h, "c_start": r["c_start"], "n": k + 1, "scr": b.scr_umol,
                     "t1_h": r["t1_h"], "t2_h": r["t2_h"], "c1": b.s1_conc, "c2": b.s2_conc, "date": b.start.date()}
        self._sz_results = {i: results[i] for i in ok_idx}
        self._sz_blocks_snapshot = blocks
        self._refresh_sec3_cards()
        self.sec3_which_label.configure(text=f"Các thẻ trên là kết quả của liều thứ {k + 1} (liều mới nhất có đủ 2 mẫu) — Mục 4 và biểu đồ dùng kết quả này.")
        n_ok = len(ok_idx)
        failed = [i + 1 for i, r in results.items() if not r["ok"]]
        if failed:
            self.sec3_status.show(
                f"⚠️ Đã tính {n_ok} liều; liều thứ {', '.join(map(str, failed))} có lỗi (xem dưới từng liều) nên KHÔNG được tính. "
                f"Mục 4 đang lấy liều thứ {k + 1} — hãy chắc đây đúng là liều bạn muốn dùng.", "warning")
        else:
            self.sec3_status.show(f"✅ Đã tính cá thể hóa {n_ok} liều có đủ 2 mẫu; Mục 4 lấy liều thứ {k + 1}.", "success")
        if self.sec4.get("cp_pred", 0) > 0:
            self.refresh_chart()
    def _refresh_sec3_cards(self):
        c = self.sec3
        self.card_ke.set_value(f"{c['ke']:.4f}")
        self.card_thalf.set_value(f"{c['thalf']:.2f}")
        self.card_vd.set_value(f"{c['vd']:.2f}")
        self.card_cp.set_value(f"{c['cp']:.2f}")
        self.card_ctr.set_value(f"{c['ctr']:.3f}")
    def _build_sz_json(self):
        """Toàn bộ dữ liệu nhập/kết quả Mục 1-3 để lưu lên Supabase (cột tdm_history.sz_json)."""
        blocks_out = []
        for i, frame in enumerate(self.sz_blocks):
            d = frame.to_dict()
            if d is None:
                continue
            res = getattr(self, "_sz_results", {}).get(i)
            if res:
                d["result"] = {"n": res["n"], "ke": res["ke"], "t_half": res["t_half"], "vd": res["vd"], "cp": res["cp"],
                               "ctr": res["ctr"], "resid_frac": res["resid_frac"]}
            blocks_out.append(d)
        return {"version": 2, "drug": self.drug_opt.get(), "severity": self.severity_opt.get(),
                "dose_mg_kg": self.dose_mg_kg_entry.get_float(5.0), "total_dose_first": getattr(self, "_total_dose", None),
                "dosing_weight": getattr(self, "_dosing_weight", None),
                "target_cp": self.target_cp_entry.get_float(20.0), "target_ctr": self.target_ctr_entry.get_float(1.0),
                "blocks": blocks_out}
    def _tdm_date(self):
        """Ngày của block TDM lưu lên Cloud = ngày bắt đầu truyền của liều mới nhất có đủ 2 mẫu."""
        return self.sec3.get("date") or datetime.date.today()
    def save_section3(self):
        msyt_input = self.msyt_entry.get().strip()
        if not msyt_input:
            self.save3_status.show("⚠️ Vui lòng nhập MSYT ở Mục 1.", "error")
            return
        if not self.sec3["calculated"]:
            self.save3_status.show("⚠️ Vui lòng nhấn nút 'Tính toán' trước khi lưu.", "warning")
            return
        tdm_date = self._tdm_date()
        date_str = tdm_date.strftime("%Y-%m-%d")
        def do_save():
            ok_info, msg_info = db.save_patient_info(
                msyt_input, self.gender_opt.get(), self.weight_entry.get_float(),
                self.height_entry.get_float(), self.age_entry.get_float(), 0)
            if not ok_info:
                self.save3_status.show(f"❌ {msg_info}", "error")
                return
            c = self.sec3
            ok_tdm, msg_tdm = db.save_sec3_data(
                msyt_input, date_str, c.get("scr") or 0.0,
                c["t1_h"], c["c1"], c["t2_h"], c["c2"],
                c["ke"], c["thalf"], c["vd"], c["cp"], c["ctr"], sz_json=self._build_sz_json())
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
        step = SOP_DOSE_RULES.get(self.drug_opt.get(), {"step": 20.0})["step"]
        hint = f" Gợi ý làm tròn liều mới: {round_to_step(new_dose_mg, step):g} mg (bội số {step:g} mg)."
        self.sec4_status.show("✅ Đã tính toán liều mới thành công." + hint, "success")
        self.refresh_chart()
    def save_section4(self):
        msyt_input = self.msyt_entry.get().strip()
        if not msyt_input:
            self.save4_status.show("⚠️ Vui lòng nhập MSYT.", "error")
            return
        if self.sec4["cp_pred"] == 0:
            self.save4_status.show("⚠️ Vui lòng nhấn nút 'Tính toán liều mới' trước.", "warning")
            return
        tdm_date = self._tdm_date()
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
            t_inf_old=c.get("t_inf", 1.0),
            tau_old=c.get("tau", 24.0),
            peak_1=c["cp"], trough_1=c["ctr"],
            dose_new=self.new_dose_entry.get_float(),
            tau_new=self.new_tau_entry.get_float(),
            t_inf_new=self.new_t_inf_entry.get_float(),
            num_cycles=num_cycles,
            c_start=c.get("c_start", 0.0),
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
        ctk.CTkButton(self.sz_container, text="👁️ Xem trước nội dung TDM sẽ xuất ra PDF", height=34,
                      fg_color="#6e7781", hover_color="#57606a",
                      command=self.preview_pdf_data).pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkLabel(self.sz_container, text="Chỉ phần các đợt TDM — không gồm thông tin hành chính bệnh nhân.",
                     font=FONT_SMALL, text_color=("gray45", "gray65")).pack(anchor="w", padx=6, pady=(0, 4))
        self.pdf_preview_box = ctk.CTkTextbox(self.sz_container, height=180, font=("Consolas", 11),
                                               state="disabled", wrap="word")
        self.pdf_preview_box.pack(fill="x", padx=6, pady=(0, 12))
        ctk.CTkButton(self.sz_container, text="📥 Tạo và Lưu file báo cáo PDF từ CSDL", height=36,
                      command=self.export_pdf).pack(fill="x", padx=6, pady=(0, 4))
        self.pdf_status = StatusLabel(self.sz_container)
        self.pdf_status.pack(fill="x", padx=6, pady=(0, 20))
    def _get_tdm_records_summary(self, records):
        """Trả về list các dict tóm tắt từng đợt TDM (Ke, t1/2, Vd, Peak/Trough thực, liều mới
        đề xuất, Cp_pred/Ctr_pred) — KHÔNG gồm thông tin hành chính bệnh nhân. Dùng CHUNG cho cả
        khung xem trước (Mục 6) và nội dung PDF thật, đảm bảo xem trước khớp 100% với PDF xuất ra."""
        summary = []
        for idx, row in enumerate(records, 1):
            ke_val = row.get("ke") or row.get("Ke") or 0
            thalf_val = row.get("thalf") or row.get("t_half") or (0.693 / ke_val if ke_val > 0 else 0)
            vd_val = row.get("vd") or row.get("Vd") or 0
            peak_val = row.get("true_peak") or row.get("peak") or 0
            trough_val = row.get("true_trough") or row.get("trough") or 0
            dose_val = row.get("new_dose") or row.get("dose") or 0
            tau_val = row.get("new_tau") or row.get("tau") or 24
            t_inf_val = row.get("new_t_inf") or row.get("t_inf") or 1
            cp_pred_val = row.get("pred_cp") or row.get("cp_pred") or row.get("cp_predicted") or 0
            ctr_pred_val = row.get("pred_ctrough") or row.get("ctr_pred") or row.get("ctr_predicted") or 0
            sz = self._parse_sz_json(row.get("sz_json")) or {}
            summary.append({
                "drug": sz.get("drug", ""), "severity": sz.get("severity", ""), "n_blocks": len(sz.get("blocks", []) or []),
                "idx": idx, "tdm_date": row.get("tdm_date", "Chưa cập nhật"),
                "ke": ke_val, "thalf": thalf_val, "vd": vd_val,
                "peak": peak_val, "trough": trough_val,
                "dose": dose_val, "tau": tau_val, "t_inf": t_inf_val,
                "cp_pred": cp_pred_val, "ctr_pred": ctr_pred_val,
            })
        return summary
    def preview_pdf_data(self):
        """Xem trước nội dung PHẦN TDM sẽ xuất ra PDF (không gồm thông tin hành chính bệnh
        nhân) — để người dùng kiểm tra lại trước khi thực sự tạo file."""
        msyt_input = self.msyt_entry.get().strip()
        self.pdf_preview_box.configure(state="normal")
        self.pdf_preview_box.delete("1.0", "end")
        if not msyt_input:
            self.pdf_preview_box.insert("1.0", "⚠️ Vui lòng nhập MSYT để xem trước.")
            self.pdf_preview_box.configure(state="disabled")
            self.pdf_status.show("⚠️ Vui lòng nhập MSYT để xem trước.", "warning")
            return
        try:
            history_res = (db.supabase.table("tdm_history").select("*")
                           .eq("msyt", msyt_input).order("tdm_date", desc=True).execute())
            records = history_res.data if history_res.data else []
            summary = self._get_tdm_records_summary(records)
            if not summary:
                text = "Chưa có lịch sử TDM nào trong CSDL cho MSYT này."
            else:
                lines = [f"Các đợt TDM sẽ đưa vào báo cáo PDF (MSYT: {msyt_input}) — {len(summary)} đợt:\n"]
                for s in summary:
                    lines.append(f"--- Đợt {s['idx']} | Ngày TDM: {s['tdm_date']} ---")
                    if s["drug"]:
                        lines.append(f"  • Thuốc: {s['drug']} | Mức độ nhiễm khuẩn: {s['severity']} | Số liều đã nhập: {s['n_blocks']}")
                    lines.append(f"  • Dược động học (PK): Ke = {s['ke']:.4f} h⁻¹, t½ = {s['thalf']:.2f} giờ, Vd = {s['vd']:.2f} lít")
                    lines.append(f"  • Nồng độ thực tế: Peak = {s['peak']:.2f} μg/mL, Trough = {s['trough']:.3f} μg/mL")
                    lines.append(f"  • Khuyến nghị liều mới: {s['dose']} mg (τ = {s['tau']}h, t' = {s['t_inf']}h)")
                    lines.append(f"  • Dự đoán tại Css: Cp_pred = {s['cp_pred']:.2f} μg/mL, Ctr_pred = {s['ctr_pred']:.3f} μg/mL")
                    lines.append("")
                text = "\n".join(lines)
            self.pdf_preview_box.insert("1.0", text)
            self.pdf_status.show(f"✅ Đã tải xem trước — {len(summary)} đợt TDM.", "success")
        except Exception as e:
            self.pdf_preview_box.insert("1.0", f"❌ Lỗi khi tải xem trước: {e}")
            self.pdf_status.show(f"❌ Lỗi khi tải xem trước: {e}", "error")
        finally:
            self.pdf_preview_box.configure(state="disabled")
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
            # SỬA LỖI (2026-09): cột thực trên bảng "patients" là "weight"/"height" (không
            # phải "weight_kg"/"height_cm") — dùng sai tên cột khiến patient_info.get(...) luôn
            # trả None, âm thầm rơi về giá trị đang gõ dở trên form thay vì dữ liệu đã lưu của
            # đúng bệnh nhân theo MSYT. Đồng thời KHÔNG dùng self._bmi/_ibw/_dosing_weight (được
            # tính từ ô nhập hiện tại trên Mục 1, có thể khác bệnh nhân đang xuất báo cáo) mà
            # tính lại BMI/IBW/Cân nặng tính liều ngay từ p_weight/p_height vừa lấy đúng từ Cloud,
            # để báo cáo luôn nhất quán với đúng MSYT được xuất, bất kể form đang hiển thị gì.
            p_age = patient_info.get("age") or self.age_entry.get_float()
            p_gender = patient_info.get("gender") or self.gender_opt.get()
            p_weight = patient_info.get("weight") or self.weight_entry.get_float()
            p_height = patient_info.get("height") or self.height_entry.get_float()
            _report_patient = PatientInfo(
                gender=p_gender, height_cm=p_height, weight_kg=p_weight,
                scr_umol=100.0, age=p_age,
                is_cf=bool(patient_info.get("is_cf", 0)))
            p_ibw = compute_ibw(_report_patient)
            p_bmi = compute_bmi(_report_patient)
            # 2. Truy vấn toàn bộ lịch sử TDM từ bảng 'tdm_history' trên Supabase
            history_res = (db.supabase.table("tdm_history").select("*")
                           .eq("msyt", msyt_input).order("tdm_date", desc=True).execute())
            records = history_res.data if history_res.data else []
            _life = True
            for _r in records:   # bản ghi mới nhất có sz_json -> lấy mức độ nhiễm khuẩn đã lưu
                _sj = self._parse_sz_json(_r.get("sz_json"))
                if _sj and _sj.get("severity"):
                    _life = _sj["severity"] == SEVERITY_LIFE
                    break
            p_dosing_weight = compute_dosing_weight(_report_patient, p_ibw, life_threatening=_life)
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
                # Dùng CHUNG hàm tóm tắt với khung xem trước (Mục 6) để đảm bảo nội dung
                # xem trước khớp 100% với PDF thật xuất ra.
                for s in self._get_tdm_records_summary(records):
                    pdf.set_font("Arial", "B", 10)
                    pdf.cell(0, 6, clean_vn_text(
                        f"--- Dot {s['idx']} | Ngay TDM: {s['tdm_date']} ---"), ln=True)
                    pdf.set_font("Arial", "", 10)
                    if s["drug"]:
                        pdf.cell(0, 5, clean_vn_text(
                            f"  + Thuoc: {s['drug']} | Muc do nhiem khuan: {s['severity']} | So lieu da nhap: {s['n_blocks']}"), ln=True)
                    pdf.cell(0, 5, clean_vn_text(
                        f"  + Duoc dong hoc (PK): Ke = {s['ke']:.4f} h-1, t1/2 = {s['thalf']:.2f} gio, "
                        f"Vd = {s['vd']:.2f} lit"), ln=True)
                    pdf.cell(0, 5, clean_vn_text(
                        f"  + Nong do thuc te: Peak = {s['peak']:.2f} ug/mL, Trough = {s['trough']:.3f} ug/mL"),
                        ln=True)
                    pdf.cell(0, 5, clean_vn_text(
                        f"  + Khuyen nghi lieu moi: {s['dose']} mg (tau = {s['tau']}h, t' = {s['t_inf']}h)"),
                        ln=True)
                    pdf.cell(0, 5, clean_vn_text(
                        f"  + Du doan tai CSS: Cp_pred = {s['cp_pred']:.2f} ug/mL, "
                        f"Ctr_pred = {s['ctr_pred']:.3f} ug/mL"), ln=True)
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
        # v16.10.26: nhiều mô hình theo thuốc; tự chọn theo thông tin bệnh nhân (người dùng vẫn đổi được)
        self.amg_model_row = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self.amg_model_row, text="Mô hình Bayesian:", font=FONT_SMALL).pack(side="left", padx=(0, 8))
        self.amg_model_var = ctk.StringVar(value=AMG_MODELS["AA2020"].label)
        self.amg_model_menu = ctk.CTkOptionMenu(self.amg_model_row, values=[AMG_MODELS["AA2020"].label],
                                                variable=self.amg_model_var, width=260,
                                                command=self._on_amg_model_manual)
        self.amg_model_menu.pack(side="left")
        self.amg_auto_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.amg_model_row, text="Tự động chọn theo thông tin bệnh nhân", variable=self.amg_auto_var,
                        font=FONT_SMALL, command=self._on_amg_auto_toggle).pack(side="left", padx=(14, 0))
        self.amg_model_note = ctk.CTkLabel(
            self, text="", font=FONT_SMALL,
            text_color=("gray45", "gray65"), wraplength=900, justify="left")
        self.amg_method_separator = ttk.Separator(self, orient="horizontal")
        self.amg_method_separator.pack(fill="x", padx=6, pady=(4, 4))
    def on_amg_method_change(self, choice=None):
        if self.amg_method_var.get() == "Bayesian":
            self.sz_container.pack_forget()
            self.amg_model_row.pack(fill="x", padx=6, pady=(0, 4), before=self.amg_method_separator)
            self.amg_model_note.pack(anchor="w", padx=6, pady=(0, 8), before=self.amg_method_separator)
            self._update_amg_drug_note()
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
        self.amg_header_label = ctk.CTkLabel(p, text="💊 TDM Bayesian — Mô hình Aréchiga-Alvarado 2020 (1 ngăn)",
                                             font=FONT_H2)
        self.amg_header_label.pack(anchor="w", padx=6, pady=(6, 4))
        self.amg_header_sub = ctk.CTkLabel(
            p, text="Dùng chung Tuổi/Giới/Cân nặng/Chiều cao ở Mục 1 phía trên. Khớp chung tất cả các mẫu; "
                    "hiệp biến chức năng thận biến thiên theo SCr.",
            font=FONT_SMALL, text_color=("gray40", "gray70"), wraplength=900, justify="left")
        self.amg_header_sub.pack(anchor="w", padx=6, pady=(0, 10))
        # --- A. Thông tin lâm sàng bổ sung (chọn mô hình + hiệp biến riêng của từng mô hình) ---
        ctk.CTkLabel(p, text="A. Thông tin lâm sàng bổ sung (để chọn mô hình và tính hiệp biến)", font=FONT_SMALL,
                     text_color=("gray30", "gray80")).pack(anchor="w", padx=6, pady=(4, 2))
        ctk.CTkLabel(p, text="Để trống albumin / CrCl nước tiểu nếu chưa có. Thiếu thông tin cần thiết → phần mềm "
                             "không tự chọn được, hãy tự chọn mô hình ở dòng 'Mô hình Bayesian' phía trên.",
                     font=FONT_SMALL, text_color=("gray45", "gray65"), wraplength=900, justify="left"
                     ).pack(anchor="w", padx=6, pady=(0, 4))
        clin = ctk.CTkFrame(p, fg_color="transparent")
        clin.pack(fill="x", padx=6)
        clin.grid_columnconfigure((0, 1, 2), weight=1, uniform="clin")
        self.amg_setting_opt = LabeledOption(clin, "Bối cảnh điều trị", list(AMG_SETTING_LABELS.values()),
                                             default=AMG_SETTING_LABELS[""])
        self.amg_setting_opt.grid(row=0, column=0, sticky="ew", padx=4)
        self.amg_albumin_entry = LabeledEntry(clin, "Albumin máu (g/L)", default="")
        self.amg_albumin_entry.grid(row=0, column=1, sticky="ew", padx=4)
        self.amg_urine_crcl_entry = LabeledEntry(clin, "CrCl đo nước tiểu 6 giờ (mL/phút) — Hodiamont", default="")
        self.amg_urine_crcl_entry.grid(row=0, column=2, sticky="ew", padx=4)
        self.amg_cf_chk = LabeledCheck(clin, "Xơ nang (cystic fibrosis)")
        self.amg_cf_chk.grid(row=1, column=0, sticky="w", padx=4)
        self.amg_ntm_chk = LabeledCheck(clin, "Bệnh phổi do NTM (mycobacteria không lao)")
        self.amg_ntm_chk.grid(row=1, column=1, sticky="w", padx=4)
        self.amg_oa_chk = LabeledCheck(clin, "Bụng hở + hút áp lực âm (NPT)")
        self.amg_oa_chk.grid(row=1, column=2, sticky="w", padx=4)
        self.amg_crrt_chk = LabeledCheck(clin, "Đang lọc máu liên tục (CRRT/CVVH)")
        self.amg_crrt_chk.grid(row=2, column=0, sticky="w", padx=4)
        self.amg_vanco_chk = LabeledCheck(clin, "Dùng kèm vancomycin")
        self.amg_vanco_chk.grid(row=2, column=1, sticky="w", padx=4)
        ctk.CTkButton(clin, text="🔄 Gợi ý lại mô hình", height=28, width=150,
                      command=lambda: self._refresh_amg_models(force_auto=True)).grid(row=2, column=2, sticky="w", padx=4)
        for w in (self.amg_setting_opt, self.amg_albumin_entry, self.amg_urine_crcl_entry, self.amg_cf_chk,
                  self.amg_ntm_chk, self.amg_oa_chk, self.amg_crrt_chk, self.amg_vanco_chk):
            w.var.trace_add("write", lambda *a: self._refresh_amg_models())
        ttk.Separator(p, orient="horizontal").pack(fill="x", padx=6, pady=14)
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
        ctk.CTkLabel(p, text="C. Lịch sử liều dùng (Truyền TM) — mỗi liều có thời gian truyền Tinf riêng",
                     font=FONT_SMALL, text_color=("gray30", "gray80")).pack(anchor="w", padx=6, pady=(4, 2))
        ctk.CTkLabel(p, text="Nhập đầy đủ các liều trước thời điểm lấy mẫu (mô hình giả định biết toàn bộ lịch sử liều). "
                             "τ chỉ dùng cho nút '➕ Tự động' và tính Cpeak/Ctrough hiện tại.",
                     font=FONT_SMALL, text_color=("gray45", "gray65"), wraplength=900, justify="left"
                     ).pack(anchor="w", padx=6, pady=(0, 4))
        self.amg_doses_container = ctk.CTkFrame(p, fg_color="transparent")
        self.amg_doses_container.pack(fill="x", padx=6)
        ctk.CTkButton(p, text="➕ Thêm liều thủ công", height=30, width=150,
                      command=lambda: self._add_amg_dose_row()).pack(anchor="w", padx=6, pady=(6, 4))
        ttk.Separator(p, orient="horizontal").pack(fill="x", padx=6, pady=14)
        # --- D. Nhiều điểm đo Cobs ---
        ctk.CTkLabel(p, text="D. Nồng độ đo được (nhiều điểm)", font=FONT_SMALL, text_color=("gray30", "gray80")
                     ).pack(anchor="w", padx=6, pady=(4, 2))
        ctk.CTkLabel(p, text="Chỉ nhập Cobs và thời điểm lấy mẫu — phần mềm tự xác định mẫu thuộc liều thứ mấy. "
                             "KHÔNG nhập mẫu dưới ngưỡng định lượng của máy đo (không có giá trị định lượng).",
                     font=FONT_SMALL, text_color=("gray45", "gray65"), wraplength=900, justify="left"
                     ).pack(anchor="w", padx=6, pady=(0, 2))
        self.amg_lloq_label = ctk.CTkLabel(p, text="", font=FONT_SMALL, text_color=("#9a6700", "#d29922"),
                                           wraplength=900, justify="left")
        self.amg_lloq_label.pack(anchor="w", padx=6, pady=(0, 4))
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
        self.amg_warn_label = ctk.CTkLabel(p, text="", font=FONT_SMALL, justify="left", anchor="w", wraplength=900)
        self.amg_warn_label.pack(fill="x", padx=10, pady=(4, 0))
        self.amg_eta_label = ctk.CTkLabel(p, text="", font=FONT_SMALL, justify="left", anchor="w", wraplength=900,
                                          text_color=("gray30", "gray75"))
        self.amg_eta_label.pack(fill="x", padx=10, pady=(4, 0))
        self.amg_points_label = ctk.CTkLabel(p, text="", font=FONT_SMALL, justify="left", anchor="w", wraplength=900,
                                             text_color=("gray30", "gray75"))
        self.amg_points_label.pack(fill="x", padx=10, pady=(2, 0))
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=(8, 0))
        row.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="ares")
        self.amg_card_cl = MetricCard(row, "CL_post (L/h)")
        self.amg_card_cl.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.amg_card_vd = MetricCard(row, "Vd_post / V1_post (L)")
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
        cols = ["Ngày TDM", "Mô hình", "CL_post", "Vd_post", "Cpeak", "Ctrough", "Liều/τ"]
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
        for w in (self.age_entry, self.weight_entry, self.height_entry, self.gender_opt):
            w.var.trace_add("write", lambda *a: self._refresh_amg_models())
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
        entries = []
        for i, r in enumerate(self.amg_scr_rows):
            try:
                entries.append(r.get_scr())
            except ValueError as e:
                raise ValueError(f"Lần đo SCr thứ {i + 1}: {e}.")
        entries.sort(key=lambda e: e[1])
        return entries
    def _get_amg_representative_scr(self):
        entries = self._get_amg_scr_entries()
        if not entries:
            raise ValueError("Chưa có lần đo SCr nào ở Mục B.")
        return entries[-1][0]
    # --- Quản lý dòng liều ---
    def _repack_amg_dose_rows(self):
        """Sắp các dòng liều theo thời điểm bắt đầu (dòng sai định dạng để cuối) rồi đánh số lại."""
        far = datetime.datetime.max
        def key(r):
            d = r.try_dose()
            t0 = d.given_at if d else parse_amg_dt_strict(r.dt_var.get())
            return t0 or far
        self.amg_dose_rows.sort(key=key)
        for r in self.amg_dose_rows:
            r.pack_forget()
        for i, r in enumerate(self.amg_dose_rows):
            r.pack(fill="x", pady=3)
            r.set_seq(i + 1)
    def _renumber_amg_doses(self):
        self._repack_amg_dose_rows()
    def _add_amg_dose_row(self, dose_default=400.0, tau_default=24.0, dt_default=None, tinf_default=1.0):
        if dt_default is None:
            last = self.amg_dose_rows[-1].try_dose() if self.amg_dose_rows else None
            if last is not None:
                dt_default = last.given_at + datetime.timedelta(hours=self.amg_dose_rows[-1].get_tau())
            else:
                dt_default = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
        row = AmgDoseRow(self.amg_doses_container, on_remove=self._remove_amg_dose_row,
                          on_auto_add=self._auto_add_amg_dose_row, dose_default=dose_default,
                          tau_default=tau_default, dt_default=dt_default, tinf_default=tinf_default)
        self.amg_dose_rows.append(row)
        self._renumber_amg_doses()
    def _auto_add_amg_dose_row(self, current_row):
        cur = current_row.try_dose()
        if cur is None:
            self.amg_solve_status.show("⚠️ Liều dùng để nhân bản chưa hợp lệ — hãy kiểm tra thời điểm/liều/Tinf của dòng đó.", "warning")
            return
        tau = current_row.get_tau()
        self._add_amg_dose_row(dose_default=cur.dose_mg, tau_default=tau,
                                dt_default=cur.given_at + datetime.timedelta(hours=tau), tinf_default=cur.t_inf_h)
    def _remove_amg_dose_row(self, row):
        if row in self.amg_dose_rows:
            self.amg_dose_rows.remove(row)
        row.destroy()
        self._renumber_amg_doses()
    def _get_amg_doses(self):
        self._repack_amg_dose_rows()
        doses = []
        for i, r in enumerate(self.amg_dose_rows):
            try:
                doses.append(r.get_dose())
            except ValueError as e:
                raise ValueError(f"Liều thứ {i + 1}: {e}.")
        doses.sort(key=lambda d: d.given_at)
        return doses
    def _find_amg_dose_row_for(self, dose):
        if dose is None:
            return None
        for r in self.amg_dose_rows:
            d = r.try_dose()
            if d is not None and d.given_at == dose.given_at:
                return r
        return None
    # --- Quản lý dòng điểm đo ---
    def _add_amg_meas_row(self, cobs_default=8.0, dt_default=None):
        row = AmgMeasRow(self.amg_meas_container, on_remove=self._remove_amg_meas_row,
                          cobs_default=cobs_default, dt_default=dt_default)
        row.pack(fill="x", pady=3)
        self.amg_meas_rows.append(row)
    def _remove_amg_meas_row(self, row):
        if row in self.amg_meas_rows:
            self.amg_meas_rows.remove(row)
        row.destroy()
    def _get_amg_measurement_pairs(self):
        """[(dòng, AmgMeasurement)] theo thứ tự dòng trên màn hình."""
        pairs = []
        for i, r in enumerate(self.amg_meas_rows):
            try:
                pairs.append((r, r.get_measurement()))
            except ValueError as e:
                raise ValueError(f"Điểm đo thứ {i + 1}: {e}.")
        return pairs
    def _get_amg_measurements(self):
        ms = [m for _, m in self._get_amg_measurement_pairs()]
        ms.sort(key=lambda m: m.t_obs)
        return ms
    # --- Chọn mô hình (v16.10.26): theo thuốc + tự động theo thông tin bệnh nhân ---
    def _amg_current_key(self):
        return model_key_from_label(self.amg_model_var.get()) or "AA2020"
    def _get_amg_clinical(self, strict=False):
        """Thông tin lâm sàng bổ sung (Mục A). strict=True: báo lỗi nếu albumin/CrCl nước tiểu sai định dạng."""
        def opt_float(entry, name, lo, hi):
            raw = str(entry.get()).strip().replace(",", ".")
            if not raw:
                return None
            try:
                v = float(raw)
            except ValueError:
                if strict:
                    raise ValueError(f"{name} không hợp lệ: {raw!r}")
                return None
            if not lo <= v <= hi:
                if strict:
                    raise ValueError(f"{name} = {v:g} ngoài khoảng cho phép {lo:g}–{hi:g}")
                return None
            return v
        setting = next((k for k, v in AMG_SETTING_LABELS.items() if v == self.amg_setting_opt.get()), "")
        return AmgClinicalInfo(
            setting=setting, cf=bool(self.amg_cf_chk.get()), ntm=bool(self.amg_ntm_chk.get()),
            open_abdomen=bool(self.amg_oa_chk.get()), crrt=bool(self.amg_crrt_chk.get()),
            vanco=bool(self.amg_vanco_chk.get()),
            albumin_gl=opt_float(self.amg_albumin_entry, "Albumin (g/L)", 5.0, 60.0),
            urine_crcl=opt_float(self.amg_urine_crcl_entry, "CrCl nước tiểu (mL/phút)", 1.0, 400.0))
    def _set_amg_clinical(self, clin):
        self.amg_setting_opt.set(AMG_SETTING_LABELS.get(clin.setting, AMG_SETTING_LABELS[""]))
        self.amg_albumin_entry.set("" if clin.albumin_gl is None else f"{clin.albumin_gl:g}")
        self.amg_urine_crcl_entry.set("" if clin.urine_crcl is None else f"{clin.urine_crcl:g}")
        self.amg_cf_chk.set(clin.cf)
        self.amg_ntm_chk.set(clin.ntm)
        self.amg_oa_chk.set(clin.open_abdomen)
        self.amg_crrt_chk.set(clin.crrt)
        self.amg_vanco_chk.set(clin.vanco)
    def _set_amg_model_key(self, key):
        self.amg_model_var.set(AMG_MODELS[key].label)
        self._update_amg_header()
    def _update_amg_header(self):
        if not hasattr(self, "amg_header_label"):
            return
        spec = AMG_MODELS.get(self._amg_current_key())
        if spec is not None:
            self.amg_header_label.configure(text=f"💊 TDM Bayesian — Mô hình {spec.label}")
    def _on_amg_model_manual(self, choice=None):
        """Người dùng tự chọn mô hình → tắt tự động chọn."""
        self.amg_auto_var.set(False)
        self._refresh_amg_models()
    def _on_amg_auto_toggle(self):
        self._refresh_amg_models(force_auto=bool(self.amg_auto_var.get()))
    def _refresh_amg_models(self, force_auto=False):
        """Cập nhật danh sách mô hình theo thuốc; nếu bật tự động thì chọn theo thông tin bệnh nhân."""
        if not hasattr(self, "amg_model_menu") or not hasattr(self, "amg_cf_chk"):
            return
        if force_auto:
            self.amg_auto_var.set(True)
        drug = self.drug_opt.get()
        keys = models_for_drug(drug)
        labels = [AMG_MODELS[k].label for k in keys]
        self.amg_model_menu.configure(values=labels or ["(không có mô hình)"])
        if not keys:
            self.amg_model_note.configure(text=f"⛔ Chưa có mô hình Bayesian cho {drug}.", text_color=("#cf222e", "#ff7b72"))
            return
        clin = self._get_amg_clinical()
        try:
            patient = self._get_amg_patient()
            scr_last = patient.scr_value
        except ValueError:
            patient = AmgPatientInfo(age=self.age_entry.get_float(50.0), gender=self.gender_opt.get(),
                                     height_cm=self.height_entry.get_float(170.0),
                                     weight_kg=self.weight_entry.get_float(70.0), scr_value=0.0)
            scr_last = None
        rec_key, why, missing = recommend_model_amg(drug, patient, clin, scr_last)
        cur = self._amg_current_key()
        if self.amg_auto_var.get():
            if rec_key is not None:
                self._set_amg_model_key(rec_key)
                self.amg_model_note.configure(text=f"🤖 Tự động chọn: {why}", text_color=("gray30", "gray75"))
            else:
                if cur not in keys:
                    self._set_amg_model_key(keys[0])
                self.amg_model_note.configure(
                    text=f"⚠️ Chưa tự chọn được mô hình: {why} Đang dùng {AMG_MODELS[self._amg_current_key()].label} "
                         "— bạn có thể tự chọn ở danh sách.", text_color=("#9a6700", "#d29922"))
        else:
            if cur not in keys:
                self._set_amg_model_key(keys[0])
                cur = keys[0]
            hint = (f" Gợi ý theo thông tin hiện có: {AMG_MODELS[rec_key].label}." if rec_key and rec_key != cur else "")
            self.amg_model_note.configure(text=f"✋ Đang tự chọn mô hình {AMG_MODELS[cur].label}.{hint}",
                                          text_color=("gray40", "gray70"))
        self._update_amg_header()
    def _amg_drug_ok(self):
        spec = AMG_MODELS.get(self._amg_current_key())
        return spec is not None and self._amg_current_key() in models_for_drug(self.drug_opt.get())
    def _update_amg_drug_note(self):
        self._refresh_amg_models()
        if hasattr(self, "amg_lloq_label"):
            lloq = get_lloq_amg(self.drug_opt.get())
            self.amg_lloq_label.configure(
                text=(f"Ngưỡng định lượng {self.drug_opt.get()}: {lloq:g} mg/L — mẫu thấp hơn sẽ bị chặn." if lloq else
                      f"⚠️ Chưa cấu hình ngưỡng định lượng (giới hạn phát hiện của máy) cho {self.drug_opt.get()}: "
                      "phần mềm chưa chặn được mẫu dưới ngưỡng, chỉ cảnh báo khi Cobs < 0,3 mg/L."),
                text_color=("gray40", "gray70") if lloq else ("#9a6700", "#d29922"))
    # --- Chạy tối ưu Bayesian (khớp chung mọi mẫu, CrCl biến thiên theo SCr) ---
    def run_amg_bayes_solve(self):
        self.amg_warn_label.configure(text="")
        self.amg_eta_label.configure(text="")
        self.amg_points_label.configure(text="")
        if self.amg_auto_var.get():
            self._refresh_amg_models()      # cập nhật lựa chọn tự động theo SCr mới nhất trước khi tính
        key = self._amg_current_key()
        spec = AMG_MODELS[key]
        if not self._amg_drug_ok():
            self.amg_bayes_result = None
            self.amg_solve_status.show(
                f"⛔ Mô hình {spec.name} không áp dụng cho {self.drug_opt.get()} (chỉ cho: {', '.join(spec.drugs)}). "
                "Hãy chọn mô hình khác hoặc dùng phương pháp Sawchuk–Zaske.", "error")
            return
        try:
            doses = self._get_amg_doses()
            pairs = self._get_amg_measurement_pairs()
            scr_entries = self._get_amg_scr_entries()
            patient = self._get_amg_patient() if scr_entries else None
            clin = self._get_amg_clinical(strict=True)
        except ValueError as e:
            self.amg_solve_status.show(f"⚠️ {e}", "warning")
            return
        if not doses:
            self.amg_solve_status.show("⚠️ Vui lòng nhập ít nhất 1 liều ở Mục C.", "warning")
            return
        if not pairs:
            self.amg_solve_status.show("⚠️ Vui lòng nhập ít nhất 1 điểm đo hợp lệ (Cobs > 0) ở Mục D.", "warning")
            return
        if not scr_entries:
            self.amg_solve_status.show("⚠️ Vui lòng nhập ít nhất 1 lần đo SCr ở Mục B.", "warning")
            return
        measurements = [m for _, m in pairs]
        # Gắn từng mẫu vào liều tương ứng (hiển thị trên từng dòng)
        assigns = assign_measurements_amg(measurements, doses)
        for (row, _), a in zip(pairs, assigns):
            if a["dose_index"] is None:
                row.set_assignment("⛔ trước liều đầu tiên — bỏ qua", warn=True)
            elif a["in_infusion"]:
                row.set_assignment(f"⚠️ thuộc liều thứ {a['dose_index'] + 1} — đang TRONG lúc truyền", warn=True)
            else:
                row.set_assignment(f"→ thuộc liều thứ {a['dose_index'] + 1}, {a['hours_after_end']:.2f} h sau khi kết thúc truyền")
        # Các mô hình đều xây dựng trên NGƯỜI LỚN: chặn dữ liệu nhân trắc ngoài khoảng hợp lý (thường do nhập sai)
        for val, lo, hi, name in ((patient.age, 18, 110, "Tuổi"), (patient.weight_kg, 25, 300, "Cân nặng (kg)"),
                                  (patient.height_cm, 120, 230, "Chiều cao (cm)")):
            if not lo <= val <= hi:
                self.amg_bayes_result = None
                self.amg_solve_status.show(f"⛔ {name} = {val:g} ngoài khoảng {lo}–{hi}: các mô hình Bayesian chỉ dành cho "
                                           "người lớn — kiểm tra lại Mục 1.", "error")
                return
        # Mẫu dưới ngưỡng định lượng (LLOQ = giới hạn phát hiện của máy đo) không có giá trị cho Bayes → CHẶN
        lloq, below = check_below_lloq_amg(self.drug_opt.get(), [m for _, m in pairs])
        if below:
            self.amg_bayes_result = None
            for row, m in pairs:
                if m in below:
                    row.set_assignment(f"⛔ dưới ngưỡng định lượng ({lloq:g} mg/L) — xóa mẫu này", warn=True)
            lst = ", ".join(f"{m.c_obs:g} mg/L lúc {m.t_obs:%d/%m %H:%M}" for m in below)
            self.amg_solve_status.show(f"⛔ Có {len(below)} mẫu dưới ngưỡng định lượng {lloq:g} mg/L ({lst}). Mẫu dưới "
                                       "ngưỡng không có giá trị định lượng — hãy xóa mẫu đó rồi chạy lại.", "error")
            return
        missing = spec.missing_inputs(clin)
        if missing:
            self.amg_bayes_result = None
            self.amg_solve_status.show(f"⚠️ Mô hình {spec.name} cần thêm: {', '.join(missing)} (Mục A).", "warning")
            return
        # Cảnh báo phạm vi áp dụng của mô hình (chỉ cảnh báo, không chặn)
        if key == "AA2020":
            warns = check_model_applicability_amg(patient, scr_entries, doses, measurements) + check_dose_overlap_amg(doses)
        else:
            warns = check_model_applicability_multi(key, patient, clin, scr_entries, doses, measurements)
        if warns:
            any_warn = any(lv == "warn" for lv, _ in warns)
            self.amg_warn_label.configure(
                text="\n".join(("⚠️ " if lv == "warn" else "ℹ️ ") + tx for lv, tx in warns),
                text_color=("#9a6700", "#d29922") if any_warn else ("gray40", "gray70"))
        if key == "AA2020":     # giữ nguyên thuật toán đã kiểm chứng của phiên bản 11/10
            result = solve_bayesian_joint_amg(patient, scr_entries, doses, measurements)
        else:
            result = solve_bayesian_multi(key, patient, clin, scr_entries, doses, measurements)
        self.amg_bayes_result = result
        if result is None or not result.success:
            self.amg_solve_status.show(f"❌ {result.message if result else 'Không có dữ liệu hợp lệ.'}", "error")
            return
        # Kiểm tra sau khớp: η chạm biên / bất thường, phần dư lớn, nồng độ rất thấp
        diag = fit_diagnostics_amg(key, clin, result)
        if diag:
            all_w = list(warns or []) + diag
            any_warn = any(lv == "warn" for lv, _ in all_w)
            diag_txt = "\n".join(("⚠️ " if lv == "warn" else "ℹ️ ") + tx for lv, tx in all_w)
            self.amg_warn_label.configure(text=diag_txt,
                                          text_color=("#9a6700", "#d29922") if any_warn else ("gray40", "gray70"))
        self.amg_measurement_used = sorted([m for m in measurements if m.t_obs > doses[0].given_at],
                                            key=lambda m: m.t_obs)
        self.amg_doses_used = doses
        self.amg_scr_used = scr_entries
        self.amg_patient_used = patient
        self.amg_model_used_key = key
        self.amg_clin_used = clin
        n_skip = len(measurements) - result.n_used
        n_skip_txt = f" (bỏ qua {n_skip} điểm đo trước liều đầu tiên)" if n_skip else ""
        if spec.renal_key is None:
            scr_txt = "mô hình không dùng hiệp biến SCr"
        else:
            scr_txt = (f"chức năng thận biến thiên theo {len(scr_entries)} lần đo SCr" if len(scr_entries) > 1
                       else "SCr không đổi (1 lần đo)")
        self.amg_solve_status.show(f"✅ [{spec.label}] {result.message} Khớp chung {result.n_used} điểm đo; "
                                   f"{scr_txt}{n_skip_txt}.", "success")
        self.amg_card_cl.set_value(f"{result.CL_optimized:.4f}")
        self.amg_card_vd.set_value(f"{result.Vd_optimized:.2f}")
        self.amg_card_ke.set_value(f"{result.Ke:.4f}")
        self.amg_card_ofv.set_value(f"{result.OFV_final:.4f}")
        if key == "AA2020":
            self.amg_eta_label.configure(text=(
                f"CrCl hiện tại = {result.crcl_current:.0f} mL/phút → CL quần thể = {result.cl_pop_current:.3f} L/h; "
                f"η_CL = {result.eta_cl * 100:+.1f}% → CL hiện tại = {result.CL_optimized:.3f} L/h.   "
                f"V quần thể = {result.vd_pop:.2f} L; η_V = {result.eta_vd * 100:+.1f}% → V = {result.Vd_optimized:.2f} L.   "
                f"(OFV: tiên nghiệm {result.ofv_prior:.3f} + quan sát {result.ofv_obs:.3f})"))
        else:
            self.amg_eta_label.configure(text=self._amg_param_text(spec, result))
        lines = []
        for i, pt in enumerate(result.points):
            n = (pt["dose_index"] + 1) if pt["dose_index"] is not None else "?"
            when = ("TRONG lúc truyền" if pt["in_infusion"] else f"{pt['hours_after_end']:.2f} h sau khi kết thúc truyền")
            lines.append(f"• Mẫu {i + 1}: {pt['t_obs']:%d/%m %H:%M} (liều thứ {n}, {when}): "
                         f"Cobs = {pt['c_obs']:g}, Cpred = {pt['c_pred']:.2f} μg/mL")
        self.amg_points_label.configure(text="\n".join(lines))
        anchor_row = self._find_amg_dose_row_for(result.anchor_dose) or (
            self.amg_dose_rows[-1] if self.amg_dose_rows else None)
        if anchor_row is not None and result.anchor_dose is not None:
            tau_used = anchor_row.get_tau()
            dose_used = result.anchor_dose.dose_mg
            tinf_used = result.anchor_dose.t_inf_h
            cpeak, ctrough = self._amg_css(dose_used, tau_used, tinf_used)
            self.amg_card_cpeak.set_value(f"{cpeak:.2f}")
            self.amg_card_ctrough.set_value(f"{ctrough:.2f}")
            self.amg_card_dose_used.set_value(f"{dose_used:g}")
            self.amg_card_tau_used.set_value(f"{tau_used:g}")
            self._amg_last_dose_used, self._amg_last_tau_used = dose_used, tau_used
            self._amg_last_cpeak, self._amg_last_ctrough = cpeak, ctrough
            # Gợi ý sẵn 1 tổ hợp liều mới (bằng liều/τ/Tinf đang dùng) — chỉ thêm nếu Mục E2 đang trống
            if not self.amg_newdose_rows:
                new_row = self._add_amg_newdose_row(dose_default=dose_used, tau_default=tau_used, tinf_default=tinf_used)
                self._compute_amg_newdose_row(new_row)
        self._refresh_amg_chart()
    def _amg_param_text(self, spec, r):
        names = {"CL": "CL (L/h)", "V1": "V1 (L)" if spec.n_cmt == 2 else "V (L)", "Q": "Q (L/h)", "V2": "V2 (L)"}
        renal_lbl = {"crcl_cg": "CrCl Cockcroft–Gault", "egfr_ckdepi_abs": "eGFR CKD-EPI tuyệt đối",
                     "egfr_mdrd175": "eGFR MDRD", "gfr_mdrd186": "GFR MDRD (Rea)"}
        head = ""
        if spec.renal_key:
            head = f"{renal_lbl.get(spec.renal_key, spec.renal_key)} hiện tại = {r.crcl_current:.0f} mL/phút. "
        parts = []
        for n in spec.param_names():
            pop, ind = r.params_pop.get(n), r.params_now.get(n)
            if n in r.etas:
                parts.append(f"{names[n]}: quần thể {pop:.3f} → cá thể {ind:.3f} (η = {r.etas[n]:+.3f})")
            else:
                parts.append(f"{names[n]}: {pop:.3f} (không có biến thiên cá thể)")
        return (head + ";   ".join(parts) +
                f".   (OFV = tiên nghiệm {r.ofv_prior:.3f} + quan sát {r.ofv_obs:.3f}; dạng −2LL như Tucuxi)")
    def _amg_css(self, dose, tau, tinf):
        """Cpeak/Ctrough trạng thái ổn định với thông số cá thể hiện tại của mô hình vừa chạy."""
        r = self.amg_bayes_result
        key = getattr(self, "amg_model_used_key", "AA2020")
        if key == "AA2020":
            return compute_css_peak_trough_amg(dose, tau, tinf, r.CL_optimized, r.Vd_optimized)
        return compute_css_peak_trough_multi(r.params_now, AMG_MODELS[key].n_cmt, dose, tau, tinf)
    def _refresh_amg_chart(self):
        r = self.amg_bayes_result
        if r is None or not r.success:
            return
        meas_list = self.amg_measurement_used or []
        t_end = (max(m.t_obs for m in meas_list) if meas_list else datetime.datetime.now()) + datetime.timedelta(hours=12)
        # CL(t) biến thiên theo SCr(t); đường cong đi qua các Cobs theo đúng mô hình đã khớp
        key = getattr(self, "amg_model_used_key", "AA2020")
        if key == "AA2020":
            times, concs = simulate_concentration_curve_amg_tv(
                self.amg_patient_used, self.amg_scr_used, self.amg_doses_used, r.eta_cl, r.Vd_optimized, t_end=t_end)
        else:
            times, concs = simulate_concentration_curve_multi(
                key, self.amg_patient_used, self.amg_clin_used, self.amg_scr_used, self.amg_doses_used, r.etas,
                t_end=t_end)
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
        cpeak, ctrough = self._amg_css(dose, tau, tinf)
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
        try:
            patient = self._get_amg_patient()
            doses_now = self._get_amg_doses()
            scr_raw_now = [row.get_raw() for row in self.amg_scr_rows]
            meas_now = self._get_amg_measurements()
        except ValueError as e:
            self.amg_save_status.show(f"⚠️ Dữ liệu nhập không hợp lệ: {e}", "warning")
            return
        # Block thông tin bệnh nhân (bảng patients, giống Sawchuk–Zaske) để tra cứu/Tab 2 thấy bệnh nhân
        clin_now = getattr(self, "amg_clin_used", None) or self._get_amg_clinical()
        ok0, msg0 = db.save_patient_info(msyt, patient.gender, patient.weight_kg, patient.height_cm, patient.age,
                                         1 if clin_now.cf else 0)
        if not ok0:
            self.amg_save_status.show(f"❌ {msg0}", "error")
            return
        r = self.amg_bayes_result
        m = self.amg_measurement_used[-1]
        date_str = m.t_obs.strftime("%Y-%m-%d")
        tau_by_time = {}
        for row in self.amg_dose_rows:
            d = row.try_dose()
            if d is not None:
                tau_by_time[d.given_at] = row.get_tau()
        doses_payload = [{"dose_mg": d.dose_mg, "given_at": d.given_at.strftime("%Y-%m-%d %H:%M"),
                          "t_inf_h": d.t_inf_h, "tau_h": tau_by_time.get(d.given_at, 24.0)} for d in doses_now]
        # SCr lưu GIÁ TRỊ GỐC + ĐƠN VỊ người dùng chọn (không quy đổi khi lưu; chỉ quy đổi 1 lần lúc tính)
        scr_payload = [{"scr": v, "unit": u, "measured_at": dt.strftime("%Y-%m-%d %H:%M")}
                       for v, u, dt in sorted(scr_raw_now, key=lambda x: x[2])]
        # v16.10.26: thuốc, mô hình, chế độ tự chọn và thông tin lâm sàng bổ sung lưu kèm trong scr_json dưới
        # dạng 1 phần tử đặc biệt {"_meta": {...}} (không cần đổi cấu trúc bảng trên Cloud)
        model_key = getattr(self, "amg_model_used_key", "AA2020")
        clin_used = getattr(self, "amg_clin_used", None) or self._get_amg_clinical()
        scr_payload.append({"_meta": {"drug": self.drug_opt.get(), "model_key": model_key,
                                      "auto": bool(self.amg_auto_var.get()), "clinical": clin_used.to_dict()}})
        meas_payload = [{"c_obs": mm.c_obs, "t_obs": mm.t_obs.strftime("%Y-%m-%d %H:%M")} for mm in meas_now]
        ok1, msg1 = db.save_amg_bayesian_patient_current(
            msyt=msyt, age=patient.age, gender=patient.gender, height=patient.height_cm,
            weight=patient.weight_kg, scr=patient.scr_value, doses_json=doses_payload,
            scr_json=scr_payload, measurements_json=meas_payload,
        )
        ok2, msg2 = db.save_amg_bayesian_result_history(
            msyt=msyt, tdm_date=date_str, model=AMG_MODELS[model_key].name,
            cl_prior=r.cl_pop_current, vd_prior=r.vd_pop,
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
        scr_raw = record.get("scr_json") or []
        if isinstance(scr_raw, str):
            try:
                scr_raw = json.loads(scr_raw)
            except Exception:
                scr_raw = []
        meta = next((it.get("_meta") for it in scr_raw if isinstance(it, dict) and "_meta" in it), None) or {}
        scr_raw = [it for it in scr_raw if isinstance(it, dict) and "_meta" not in it]
        # Bản ghi cũ (trước v16.10.26) không có _meta: chỉ có Amikacin + Aréchiga-Alvarado 2020
        drug_saved = meta.get("drug") if meta.get("drug") in DRUG_LIST else next(
            (d for d in DRUG_LIST if 'amikacin' in d.lower()), self.drug_opt.get())
        self.drug_opt.set(drug_saved)
        self._set_amg_clinical(AmgClinicalInfo.from_dict(meta.get("clinical")))
        saved_key = meta.get("model_key") if meta.get("model_key") in AMG_MODELS else "AA2020"
        self.amg_auto_var.set(bool(meta.get("auto", False)))
        self._set_amg_model_key(saved_key)
        self._refresh_amg_models()
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
        parsed = sorted([(parse_float(it.get("dose_mg"), 0.0), parse_amg_dt(it.get("given_at")), it)
                          for it in doses_raw], key=lambda x: x[1])
        if parsed:
            for i, (dose_mg, given_at, it) in enumerate(parsed):
                tau = parse_float(it.get("tau_h"), 0.0)
                if tau <= 0:   # bản ghi cũ: suy τ từ khoảng cách tới liều kế tiếp
                    tau = (parsed[i + 1][1] - given_at).total_seconds() / 3600.0 if i + 1 < len(parsed) else 24.0
                # Bản ghi cũ không có t_inf_h theo liều -> mặc định 1 h (giá trị cũ nằm ở từng điểm đo)
                self._add_amg_dose_row(dose_default=dose_mg, tau_default=(tau if tau > 0 else 24.0),
                                       dt_default=given_at, tinf_default=parse_float(it.get("t_inf_h"), 1.0))
        else:
            self._add_amg_dose_row()
        for row in list(self.amg_scr_rows):
            self._remove_amg_scr_row(row)
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
                                        dt_default=parse_amg_dt(it.get("t_obs")))
        else:
            self._add_amg_meas_row()
        self._refresh_amg_models()
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
            model_name = str(row.get("model") or "Aréchiga-Alvarado 2020")
            self.amg_prev_tree.insert("", "end", values=(d_date, model_name, cl, vd, cpeak, ctrough, dose_tau))
        self.amg_load_status.show(f"✅ Đã tải dữ liệu Bayesian cho MSYT {msyt}.", "success")

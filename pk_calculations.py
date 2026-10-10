"""
pk_calculations.py — Các hàm tính toán Dược động học (PK) cho TDM Aminoglycosid
"""
import math
import datetime
import numpy as np
from dataclasses import dataclass, replace
from typing import Optional
@dataclass
class PatientInfo:
    gender: str
    height_cm: float
    weight_kg: float
    scr_umol: float
    age: float
    is_cf: bool = False
@dataclass
class InitialDoseInput:
    dose_mg_per_kg: float
    infusion_time_h: float
    tau_h: float
    target_cp: float
    target_ctrough: float
@dataclass
class MeasuredLevels:
    # n_doses: mẫu được lấy sau liều thứ mấy của chế độ liều hiện tại (1 = liều đầu tiên,
    # chưa tích lũy). None hoặc >= 50 được hiểu là đã đạt trạng thái ổn định (steady state).
    n_doses: Optional[int]
    t1_h: float
    c1: float
    t2_h: float
    c2: float
    infusion_time_h: float
    tau_h: float
    total_dose_mg: float
@dataclass
class DoseAdjustment:
    new_dose_mg: float
    new_tau_h: float
# ==========================================
# CÁC HÀM TÍNH TOÁN QUẦN THỂ & LÝ THUYẾT
# ==========================================
def compute_bmi(patient: PatientInfo) -> float:
    height_m = patient.height_cm / 100.0
    if height_m <= 0:
        return 0.0
    return patient.weight_kg / (height_m ** 2)
def compute_ibw(patient: PatientInfo) -> float:
    height_inch = patient.height_cm / 2.54
    over_60_inch = max(0.0, height_inch - 60.0)
    if patient.gender.lower() in ['nam', 'male', 'm']:
        return 50.0 + 2.3 * over_60_inch
    else:
        return 45.5 + 2.3 * over_60_inch
def compute_dosing_weight(patient: PatientInfo, ibw: float, life_threatening: bool = True) -> float:
    """Cân nặng tính liều mg/kg.
    - Nhiễm khuẩn ĐE DỌA TÍNH MẠNG (mặc định, giữ hành vi cũ): BMI <= 30 dùng cân nặng thực (TBW,
      ưu tiên đạt nồng độ đỉnh), BMI > 30 dùng AdjBW (40%).
    - Không đe dọa tính mạng: theo quy trình (ABW < IBW -> ABW; <= 130% IBW -> IBW; > 130% -> AdjBW)."""
    if not life_threatening:
        return compute_weight_for_crcl(patient, ibw)
    bmi = compute_bmi(patient)
    if bmi > 30.0:
        return ibw + 0.4 * (patient.weight_kg - ibw)
    else:
        return patient.weight_kg
def compute_weight_for_crcl(patient: PatientInfo, ibw: float) -> float:
    """Cân nặng dùng cho Cockcroft-Gault theo quy trình (Phụ lục 2, mục 1):
    ABW < IBW -> ABW; IBW <= ABW <= 130% IBW -> IBW; ABW > 130% IBW -> AdjBW (40%).
    (Khác với cân nặng tính liều mg/kg ở compute_dosing_weight.)"""
    abw = patient.weight_kg
    if abw < ibw:
        return abw
    if abw <= 1.3 * ibw:
        return ibw
    return ibw + 0.4 * (abw - ibw)
def compute_crcl(patient: PatientInfo, bmi: float = None, ibw: float = None, dosing_weight: float = None) -> float:
    # bmi, dosing_weight giữ lại chỉ để tương thích chữ ký cũ, KHÔNG còn dùng.
    if ibw is None:
        ibw = compute_ibw(patient)
    weight_for_cg = compute_weight_for_crcl(patient, ibw)
    scr_mg_dl = patient.scr_umol / 88.4
    if scr_mg_dl <= 0:
        return 0.0
    factor = 1.0 if patient.gender.lower() in ['nam', 'male', 'm'] else 0.85
    crcl = ((140.0 - patient.age) * weight_for_cg * factor) / (72.0 * scr_mg_dl)
    return max(0.0, crcl)
def compute_ke_population(crcl: float) -> float:
    return 0.00293 * crcl + 0.014
def compute_t_half(ke: float) -> float:
    if ke <= 0:
        return 0.0
    return np.log(2.0) / ke
def compute_vd_population(dosing_weight: float, is_cf: bool) -> float:
    factor = 0.35 if is_cf else 0.25
    return factor * dosing_weight
def compute_total_dose(dose_mg_per_kg: float, dosing_weight: float) -> float:
    return dose_mg_per_kg * dosing_weight
def compute_suggested_tau(target_cp: float, target_ctrough: float, ke: float, infusion_time_h: float) -> float:
    if target_ctrough <= 0 or target_cp <= 0 or ke <= 0:
        return 24.0
    ratio = target_cp / target_ctrough
    if ratio <= 1.0:
        return 24.0
    tau = np.log(ratio) / ke + infusion_time_h
    return max(8.0, round(tau / 4.0) * 4.0)
def compute_predicted_cp_population(total_dose: float, target_cp: float, ke: float, tau_h: float) -> float:
    return target_cp
def compute_predicted_ctrough_population(cp_pred: float, ke: float, tau_h: float, infusion_time_h: float) -> float:
    t_decline = max(0.0, tau_h - infusion_time_h)
    return cp_pred * np.exp(-ke * t_decline)

# ==========================================
# LIỀU ĐẦU THEO QUY TRÌNH: GIỚI HẠN TỐI ĐA + LÀM TRÒN
# ==========================================
DRUG_GENTAMICIN = "Gentamicin"
DRUG_TOBRAMYCIN = "Tobramycin"
DRUG_AMIKACIN = "Amikacin"
DRUG_LIST = [DRUG_GENTAMICIN, DRUG_TOBRAMYCIN, DRUG_AMIKACIN]
SEVERITY_NORMAL = "Không đe dọa tính mạng"
SEVERITY_LIFE = "Đe dọa tính mạng (sốc NK)"
SEVERITY_LIST = [SEVERITY_NORMAL, SEVERITY_LIFE]
# Quy trình, Phụ lục 2 mục 2: liều đầu tối đa và bước làm tròn (mg)
SOP_DOSE_RULES = {
    # mgkg_*: khoảng mg/kg khuyến cáo của quy trình cho liều ĐẦU (không đe dọa / đe dọa tính mạng)
    DRUG_GENTAMICIN: {"step": 20.0, "cap_normal": 500.0, "cap_life": 700.0,
                      "mgkg_normal": (4.0, 5.0), "mgkg_life": (5.0, 7.0)},
    DRUG_TOBRAMYCIN: {"step": 20.0, "cap_normal": 500.0, "cap_life": 700.0,
                      "mgkg_normal": (4.0, 5.0), "mgkg_life": (5.0, 7.0)},
    DRUG_AMIKACIN: {"step": 50.0, "cap_normal": 2000.0, "cap_life": 3000.0,
                    "mgkg_normal": (15.0, 20.0), "mgkg_life": (20.0, 30.0)},
}
def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step + 0.5) * step
def compute_initial_dose_sop(dose_mg_per_kg: float, dosing_weight: float, drug: str, life_threatening: bool) -> dict:
    """Liều đầu = mg/kg x cân nặng tính liều, GIỚI HẠN tối đa theo thuốc/mức độ nhiễm khuẩn rồi
    LÀM TRÒN (gentamicin/tobramycin 20 mg, amikacin 50 mg) theo quy trình."""
    rule = SOP_DOSE_RULES.get(drug, SOP_DOSE_RULES[DRUG_GENTAMICIN])
    raw = dose_mg_per_kg * dosing_weight
    cap = rule["cap_life"] if life_threatening else rule["cap_normal"]
    capped = raw > cap
    final = round_to_step(min(raw, cap), rule["step"])
    lo, hi = rule["mgkg_life"] if life_threatening else rule["mgkg_normal"]
    status = "high" if dose_mg_per_kg > hi + 1e-9 else ("low" if dose_mg_per_kg < lo - 1e-9 else "ok")
    return {"raw": raw, "cap": cap, "step": rule["step"], "was_capped": capped, "final": final,
            "mgkg_min": lo, "mgkg_max": hi, "mgkg_status": status}
# ==========================================
# THỜI ĐIỂM LẤY MẪU 2 ĐIỂM THEO QUY TRÌNH + ĐỘ TIN CẬY
# ==========================================
SOP_T1_H = 2.0                 # T1 = 2 giờ kể từ lúc BẮT ĐẦU truyền (mọi mức CrCl)
ASSAY_CV = 0.05                # GIẢ ĐỊNH sai số xét nghiệm tương đối mỗi mẫu (5%)
T1_TOL_H = 0.5                 # dung sai so với T1 của quy trình
T2_TOL_H = 1.0                 # dung sai so với T2 của quy trình
MIN_POST_INFUSION_H = 0.5      # T1 nên cách cuối truyền >= 0,5 h (qua pha phân bố)
def sop_sampling_times(crcl: float):
    """Quy trình: CrCl > 90 -> T2 = 6 h; 40-90 -> 10 h; < 40 -> 15 h (T1 luôn 2 h)."""
    if crcl > 90.0:
        return SOP_T1_H, 6.0, "CrCl > 90"
    if crcl >= 40.0:
        return SOP_T1_H, 10.0, "CrCl 40-90"
    return SOP_T1_H, 15.0, "CrCl < 40"
def ke_relative_error(ke: float, t1: float, t2: float, assay_cv: float = ASSAY_CV) -> float:
    """Sai số tương đối (1 SD) của Ke = ln(C1/C2)/(t2-t1) khi mỗi nồng độ có sai số tương đối assay_cv:
    SD[ln C1 - ln C2] = sqrt(2).assay_cv  =>  CV(Ke) = sqrt(2).assay_cv / (Ke.(t2-t1))."""
    dt = t2 - t1
    if ke <= 0 or dt <= 0:
        return float("inf")
    return math.sqrt(2.0) * assay_cv / (ke * dt)
def check_sampling_times(t1: float, t2: float, t_inf: float, tau: float, ke: float,
                         crcl: Optional[float] = None, assay_cv: float = ASSAY_CV) -> dict:
    """Kiểm tra cặp (T1, T2) người dùng nhập. Trả {"items": [(mức, nội dung)], "worst": mức,
    "cv_ke", "t_half", "t_half_range"}. mức: 'error' | 'warn' | 'info'. ke dùng để ước lượng t1/2
    và sai số (có thể là Ke quần thể theo CrCl hoặc Ke cá thể đã đo)."""
    items = []
    if t2 <= t1:
        items.append(("error", "T2 phải lớn hơn T1."))
        return {"items": items, "worst": "error", "cv_ke": float("inf"), "t_half": None, "t_half_range": None}
    if t_inf > 0 and t1 < t_inf:
        items.append(("error", f"T1 ({t1:g} h) nằm TRONG thời gian truyền ({t_inf:g} h) — quy trình: không lấy máu trong lúc truyền."))
    elif t_inf > 0 and (t1 - t_inf) < MIN_POST_INFUSION_H:
        items.append(("warn", f"T1 chỉ cách cuối truyền {t1 - t_inf:.2f} h (< {MIN_POST_INFUSION_H:g} h): còn trong pha phân bố, "
                              "đỉnh ngoại suy có thể bị phóng đại và Ke bị tính cao."))
    if tau > 0 and t2 > tau:
        items.append(("warn", f"T2 ({t2:g} h) vượt quá τ ({tau:g} h): mẫu 2 có thể chịu ảnh hưởng liều kế tiếp."))
    if crcl is not None:
        s1, s2, band = sop_sampling_times(crcl)
        if abs(t1 - s1) > T1_TOL_H or abs(t2 - s2) > T2_TOL_H:
            items.append(("warn", f"Lệch quy trình: với {band} (CrCl ≈ {crcl:.0f} mL/phút) nên lấy T1 ≈ {s1:g} h và T2 ≈ {s2:g} h "
                                  f"(đang nhập T1 = {t1:g} h, T2 = {t2:g} h)."))
        else:
            items.append(("info", f"Khớp quy trình ({band}: T1 ≈ {s1:g} h, T2 ≈ {s2:g} h)."))
    t_half = t_half_range = None
    cv = float("inf")
    if ke and ke > 0:
        t_half = math.log(2.0) / ke
        dt = t2 - t1
        cv = ke_relative_error(ke, t1, t2, assay_cv)
        if dt < t_half:
            items.append(("warn", f"Khoảng cách T2 − T1 = {dt:g} h < 1 t½ (t½ ≈ {t_half:.1f} h): Ke sẽ kém chính xác."))
        lo = ke * (1 - cv) if cv < 1 else None
        hi = ke * (1 + cv)
        t_half_range = (math.log(2.0) / hi, (math.log(2.0) / lo) if lo else None)
        rng = (f"{t_half_range[0]:.1f}–{t_half_range[1]:.1f} h" if t_half_range[1] else f"> {t_half_range[0]:.1f} h")
        items.append(("warn" if cv > 0.15 else "info",
                      f"Sai số Ke ước tính ≈ ±{cv * 100:.0f}% (giả định sai số xét nghiệm {assay_cv * 100:.0f}%/mẫu) "
                      f"→ t½ khoảng {rng} (Ke ≈ {ke:.3f} h⁻¹, t½ ≈ {t_half:.1f} h)."))
    order = {"error": 2, "warn": 1, "info": 0}
    worst = max((lv for lv, _ in items), key=lambda x: order[x], default="info")
    return {"items": items, "worst": worst, "cv_ke": cv, "t_half": t_half, "t_half_range": t_half_range}
# ==========================================
# CÁC HÀM TÍNH TOÁN CÁ THỂ HÓA TDM & HIỆU CHỈNH
# ==========================================
def compute_ke_individual(measured: MeasuredLevels) -> float:
    if measured.t2_h <= measured.t1_h or measured.c1 <= 0 or measured.c2 <= 0:
        return 0.0
    return np.log(measured.c1 / measured.c2) / (measured.t2_h - measured.t1_h)
def compute_t_half_individual(ke_ind: float) -> float:
    return compute_t_half(ke_ind)
def compute_true_peak(measured: MeasuredLevels, ke_ind: float) -> float:
    if ke_ind <= 0:
        return measured.c1
    if measured.t1_h >= measured.infusion_time_h:
        return measured.c1 * np.exp(ke_ind * (measured.t1_h - measured.infusion_time_h))
    else:
        return measured.c1
def compute_true_trough(true_peak: float, ke_ind: float, infusion_time_h: float, tau_h: float) -> float:
    t_decline = max(0.0, tau_h - infusion_time_h)
    return true_peak * np.exp(-ke_ind * t_decline)
def accumulation_factor(ke: float, tau: float, n_doses: Optional[int]) -> float:
    """R = (1 - e^(-n.ke.tau)) / (1 - e^(-ke.tau)): hệ số tích lũy ngay sau liều thứ n
    (các liều giống nhau, cùng tau). n = 1 -> R = 1 (liều đầu); n -> vô hạn -> steady state."""
    d = 1 - np.exp(-ke * tau)
    if d <= 0:
        return 1.0
    if n_doses is None or n_doses >= 50:
        return 1.0 / d
    return (1 - np.exp(-n_doses * ke * tau)) / d
def compute_vd_individual_exact(dose_mg: float, ke: float, peak: float, t_inf: float, tau: float, n_doses: Optional[int]) -> float:
    # Cpeak(sau liều thứ n) = D(1-e^(-ke.t'))/(t'.ke.V) . R  =>  V = D(1-e^(-ke.t')).R/(t'.ke.Cpeak)
    # n = 1 trùng công thức liều đầu của quy trình; n lớn trùng công thức steady state.
    if isinstance(n_doses, bool):  # tương thích cũ: True = liều đầu, False = steady state
        n_doses = 1 if n_doses else None
    num = dose_mg * (1 - np.exp(-ke * t_inf)) * accumulation_factor(ke, tau, n_doses)
    den = t_inf * ke * peak
    return num / den if den > 0 else 0.0
def compute_vd_individual(dose_mg: float, ke: float, peak: float, t_inf: float, tau: float, n_doses: Optional[int]) -> float:
    return compute_vd_individual_exact(dose_mg, ke, peak, t_inf, tau, n_doses)
def compute_cp_predicted_adjusted(dose_new: float, ke: float, vd_ind: float, t_inf_new: float, tau_new: float) -> float:
    num = dose_new * (1 - np.exp(-ke * t_inf_new))
    den = t_inf_new * vd_ind * ke * (1 - np.exp(-ke * tau_new))
    return num / den if den > 0 else 0.0
def compute_predicted_cp_adjusted(dose_new: float, ke: float, vd_ind: float, t_inf_new: float, tau_new: float) -> float:
    return compute_cp_predicted_adjusted(dose_new, ke, vd_ind, t_inf_new, tau_new)
def compute_ctrough_predicted_adjusted(cp_pred: float, ke: float, t_inf_new: float, tau_new: float) -> float:
    return cp_pred * np.exp(-ke * (tau_new - t_inf_new))
def compute_predicted_ctrough_adjusted(cp_pred: float, ke: float, t_inf_new: float, tau_new: float) -> float:
    return compute_ctrough_predicted_adjusted(cp_pred, ke, t_inf_new, tau_new)
# ==========================================
# HÀM MÔ PHỎNG ĐỒ THỊ NHIỀU CHU KỲ LIỀU
# ==========================================
def simulate_dosing_curve(ke, vd, t_inf_old, tau_old, peak_1, trough_1, dose_new, tau_new, t_inf_new, num_cycles=10, c_start=0.0):
    times = []
    concs = []
    current_time_offset = 0.0
    c_min_prev = 0.0
    for cycle in range(1, num_cycles + 1):
        if cycle == 1:
            current_tau = tau_old
            c_max = peak_1
            t_inf_curr = t_inf_old
            t_inf_pts = np.linspace(0, t_inf_curr, 20)
            for t_rel in t_inf_pts:
                c_t = (c_start + (c_max - c_start) * t_rel / t_inf_curr) if t_inf_curr > 0 else c_max
                times.append(current_time_offset + t_rel)
                concs.append(c_t)
            t_elim_pts = np.linspace(t_inf_curr, current_tau, 80)
            for t_rel in t_elim_pts[1:]:
                c_t = c_max * np.exp(-ke * (t_rel - t_inf_curr))
                times.append(current_time_offset + t_rel)
                concs.append(c_t)
            c_min_prev = c_max * np.exp(-ke * (current_tau - t_inf_curr))
            current_time_offset += current_tau
        else:
            current_tau = tau_new
            t_inf_curr = t_inf_new
            c_max = (dose_new * (1 - np.exp(-ke * t_inf_curr))) / (t_inf_curr * vd * ke) + c_min_prev * np.exp(-ke * t_inf_curr)
            t_inf_pts = np.linspace(0, t_inf_curr, 20)
            for t_rel in t_inf_pts:
                c_t = (dose_new * (1 - np.exp(-ke * t_rel))) / (t_inf_curr * vd * ke) + c_min_prev * np.exp(-ke * t_rel)
                times.append(current_time_offset + t_rel)
                concs.append(c_t)
            t_elim_pts = np.linspace(t_inf_curr, current_tau, 80)
            for t_rel in t_elim_pts[1:]:
                c_t = c_max * np.exp(-ke * (t_rel - t_inf_curr))
                times.append(current_time_offset + t_rel)
                concs.append(c_t)
            c_min_prev = c_max * np.exp(-ke * (current_tau - t_inf_curr))
            current_time_offset += current_tau
    return np.array(times), np.array(concs)
def simulate_dosing_curve_custom(ke, vd, t_inf_old, tau_old, peak_1, trough_1, dose_new, tau_new, t_inf_new, num_cycles=10, c_start=0.0):
    return simulate_dosing_curve(ke, vd, t_inf_old, tau_old, peak_1, trough_1, dose_new, tau_new, t_inf_new, num_cycles, c_start)
# ==========================================
# NHIỀU LIỀU THỰC TẾ: CỘNG DỒN + KIỂM TRA THỜI ĐIỂM LẤY MẪU THEO TỪNG LIỀU
# ==========================================
DT_FORMAT = "%d/%m/%Y %H:%M"
def parse_sz_datetime(text):
    """Đọc 'dd/mm/yyyy hh:mm' (hoặc ISO 'yyyy-mm-dd hh:mm'). Sai định dạng -> None (KHÔNG tự lấy giờ hiện tại)."""
    s = str(text or "").strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
def format_sz_datetime(dt):
    return dt.strftime(DT_FORMAT) if dt else ""
def _hours(a, b):
    return (b - a).total_seconds() / 3600.0
@dataclass
class DoseBlock:
    """Một liều thực tế + (tuỳ chọn) 2 mẫu định lượng lấy trong khoảng liều đó."""
    start: datetime.datetime                 # thời điểm BẮT ĐẦU truyền
    dose_mg: float
    tau_h: float
    t_inf_h: float
    scr_umol: Optional[float] = None
    s1_time: Optional[datetime.datetime] = None
    s1_conc: Optional[float] = None
    s2_time: Optional[datetime.datetime] = None
    s2_conc: Optional[float] = None
    def has_pair(self) -> bool:
        return (self.s1_time is not None and self.s2_time is not None
                and self.s1_conc is not None and self.s2_conc is not None
                and self.s1_conc > 0 and self.s2_conc > 0)
    def has_any_sample(self) -> bool:
        return self.s1_time is not None or self.s2_time is not None or bool(self.s1_conc) or bool(self.s2_conc)
def compute_block_individual(blocks, idx: int, assay_cv: float = ASSAY_CV) -> dict:
    """Cá thể hóa (Sawchuk-Zaske) cho liều thứ idx+1 bằng 2 mẫu của chính liều đó, CÓ TÍNH các liều trước.
    - Ke = ln(C1/C2)/(T2-T1)   (mọi liều trước đều thải trừ cùng Ke nên độ dốc giữa 2 mẫu vẫn đúng)
    - Cp thật (tại cuối truyền liều thứ n) = C1 . e^(Ke.(T1 - t'))      (đã gồm tồn dư các liều trước)
    - Vd = [ Sum_j D_j(1-e^(-Ke.t'_j))/(t'_j.Ke) . e^(-Ke.dt_j) ] / Cp   (dt_j: từ cuối truyền liều j đến cuối truyền liều n)
      Liều thứ 1 -> trùng công thức liều đầu D(1-e^(-Ke.t'))/(t'.Ke.Cp); nhiều liều giống nhau -> trùng hệ số tích lũy.
    Giả định: các liều trước đã được nhập ĐẦY ĐỦ và Ke không đổi trong giai đoạn đó."""
    res = {"ok": False, "n": idx + 1, "messages": [], "ke": 0.0, "t_half": 0.0, "vd": 0.0, "cp": 0.0, "ctr": 0.0,
           "cp_this": 0.0, "resid_frac": 0.0, "c_start": 0.0, "t1_h": None, "t2_h": None, "cv_ke": None}
    msgs = res["messages"]
    b = blocks[idx]
    err = lambda t: msgs.append(("error", t))
    if not b.has_pair():
        err("Chưa đủ 2 mẫu (thời điểm + nồng độ > 0).")
        return res
    if b.dose_mg <= 0 or b.t_inf_h <= 0 or b.tau_h <= 0:
        err("Liều thực tế, thời gian truyền và τ phải lớn hơn 0.")
        return res
    for j in range(idx):
        pj = blocks[j]
        if pj.start >= b.start:
            err(f"Liều thứ {j + 1} phải bắt đầu TRƯỚC liều thứ {idx + 1} (kiểm tra thứ tự/thời điểm).")
        elif pj.start + datetime.timedelta(hours=pj.t_inf_h) > b.start:
            err(f"Liều thứ {j + 1} chưa truyền xong khi liều thứ {idx + 1} bắt đầu (chồng thời gian truyền).")
    t1h, t2h = _hours(b.start, b.s1_time), _hours(b.start, b.s2_time)
    res["t1_h"], res["t2_h"] = t1h, t2h
    if t2h <= t1h:
        err("Thời điểm định lượng 2 phải SAU thời điểm định lượng 1.")
    if b.s1_conc <= b.s2_conc and t2h > t1h:
        err("Nồng độ 1 phải lớn hơn nồng độ 2 (hai mẫu trong cùng khoảng liều, sau đỉnh).")
    if idx + 1 < len(blocks):
        nxt = blocks[idx + 1]
        if b.s2_time >= nxt.start or b.s1_time >= nxt.start:
            err(f"Mẫu lấy sau khi liều thứ {idx + 2} đã bắt đầu — hai mẫu phải nằm trong khoảng liều thứ {idx + 1}.")
        gap = _hours(b.start, nxt.start)
        if abs(gap - b.tau_h) > 0.5:
            msgs.append(("warn", f"τ nhập ({b.tau_h:g} h) khác khoảng thực tế tới liều kế tiếp ({gap:.1f} h)."))
    if any(l == "error" for l, _ in msgs):
        return res
    ke = math.log(b.s1_conc / b.s2_conc) / (t2h - t1h)
    qc = check_sampling_times(t1h, t2h, b.t_inf_h, b.tau_h if idx + 1 == len(blocks) else 0.0, ke, crcl=None, assay_cv=assay_cv)
    for lv, tx in qc["items"]:
        if lv == "error":
            err(tx)
        else:
            msgs.append((lv, tx))
    if any(l == "error" for l, _ in msgs):
        return res
    cp_total = b.s1_conc * math.exp(ke * (t1h - b.t_inf_h))
    end_b = b.start + datetime.timedelta(hours=b.t_inf_h)
    def a_j(blk):
        return blk.dose_mg * (1 - math.exp(-ke * blk.t_inf_h)) / (blk.t_inf_h * ke)
    s_total, s_prior_at_start = 0.0, 0.0
    for j in range(idx + 1):
        pj = blocks[j]
        end_j = pj.start + datetime.timedelta(hours=pj.t_inf_h)
        s_total += a_j(pj) * math.exp(-ke * _hours(end_j, end_b))
        if j < idx:
            s_prior_at_start += a_j(pj) * math.exp(-ke * _hours(end_j, b.start))
    vd = s_total / cp_total
    cp_this = a_j(b) / vd
    res.update({"ok": True, "ke": ke, "t_half": math.log(2.0) / ke, "vd": vd, "cp": cp_total,
                "ctr": cp_total * math.exp(-ke * max(0.0, b.tau_h - b.t_inf_h)),
                "cp_this": cp_this, "resid_frac": max(0.0, 1.0 - cp_this / cp_total),
                "c_start": s_prior_at_start / vd, "cv_ke": qc["cv_ke"]})
    if idx == 0:
        msgs.insert(0, ("info", "Liều thứ 1: công thức liều đầu (chưa tích lũy)."))
    else:
        msgs.insert(0, ("info", f"Liều thứ {idx + 1}: cộng dồn {idx} liều trước; tồn dư các liều trước chiếm "
                                f"{res['resid_frac'] * 100:.0f}% đỉnh đo được (giả định các liều trước đã nhập đầy đủ)."))
    prev = blocks[idx - 1] if idx > 0 else None
    if prev and b.scr_umol and prev.scr_umol and prev.scr_umol > 0:
        change = abs(b.scr_umol - prev.scr_umol) / prev.scr_umol
        if change >= 0.25:
            msgs.append(("warn", f"SCr thay đổi {change * 100:.0f}% so với liều trước (≥ 25%): Ke có thể không còn như trước, "
                                 "kết quả cộng dồn kém tin cậy."))
    return res
def sop_check_blocks(blocks, patient: PatientInfo, assay_cv: float = ASSAY_CV) -> list:
    """Kiểm tra LẦN LƯỢT từng liều theo quy trình. Mỗi phần tử: {idx, n, level, lines}.
    Liều nào có mẫu lệch khuyến cáo -> cảnh báo theo cú pháp: 'Liều thứ n có CrCl = ... mL/phút, ước lượng t½ = ... h,
    khuyến cáo lấy mẫu T1 = ... và T2 = ...'. Liều chưa nhập mẫu -> hiển thị khuyến cáo để lên kế hoạch."""
    out = []
    for i, b in enumerate(blocks):
        n = i + 1
        item = {"idx": i, "n": n, "level": "info", "lines": []}
        scr = b.scr_umol
        if scr is None or scr <= 0:
            item["level"] = "warn"
            item["lines"].append(("warn", f"Liều thứ {n}: thiếu SCr nên chưa tính được CrCl và khuyến cáo T1/T2."))
            out.append(item)
            continue
        pt = replace(patient, scr_umol=scr)
        ibw = compute_ibw(pt)
        crcl = compute_crcl(pt, ibw=ibw)
        ke_pop = compute_ke_population(crcl)
        t_half_pop = math.log(2.0) / ke_pop
        s1, s2, band = sop_sampling_times(crcl)
        rec1 = b.start + datetime.timedelta(hours=s1)
        rec2 = b.start + datetime.timedelta(hours=s2)
        head = (f"Liều thứ {n} có CrCl = {crcl:.0f} mL/phút, ước lượng t½ = {t_half_pop:.1f} h, "
                f"khuyến cáo lấy mẫu T1 = {format_sz_datetime(rec1)} (sau {s1:g} h) và T2 = {format_sz_datetime(rec2)} (sau {s2:g} h)")
        if not b.has_any_sample():
            item["lines"].append(("info", head + " — chưa nhập mẫu."))
            out.append(item)
            continue
        if b.s1_time is None or b.s2_time is None:
            item["level"] = "warn"
            item["lines"].append(("warn", head + ". Mới nhập một thời điểm lấy mẫu."))
            out.append(item)
            continue
        t1h, t2h = _hours(b.start, b.s1_time), _hours(b.start, b.s2_time)
        deviates = abs(t1h - s1) > T1_TOL_H or abs(t2h - s2) > T2_TOL_H
        lv = "warn" if deviates else "info"
        item["lines"].append((lv, (head + f". Đang nhập: T1 = {t1h:.2f} h, T2 = {t2h:.2f} h." if deviates
                                   else f"Liều thứ {n}: T1 = {t1h:.2f} h, T2 = {t2h:.2f} h khớp quy trình ({band}, CrCl = {crcl:.0f} mL/phút).")))
        ke_use, src = ke_pop, "Ke ước theo CrCl"
        if b.has_pair() and b.s1_conc > b.s2_conc and t2h > t1h:
            ke_use, src = math.log(b.s1_conc / b.s2_conc) / (t2h - t1h), "Ke đo được từ 2 mẫu"
        qc = check_sampling_times(t1h, t2h, b.t_inf_h, 0.0, ke_use, crcl=None, assay_cv=assay_cv)
        for l2, tx in qc["items"]:
            item["lines"].append((l2, f"Liều thứ {n} ({src}): {tx}"))
        order = {"error": 2, "warn": 1, "info": 0}
        item["level"] = max((l for l, _ in item["lines"]), key=lambda x: order[x])
        out.append(item)
    return out

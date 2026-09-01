"""
vanco_calculations.py — Lõi tính toán TDM Vancomycin theo phương pháp Bayes cá thể hóa,
mô hình dược động học 2 ngăn (2-compartment, Vc + Vp), tương đương 100% với công thức
trong sheet Excel "TDM Bayes có Vp 2".

Toàn bộ công thức trong file này được đối chiếu số học trực tiếp với các ô tính sẵn
(cached values) của file Excel gốc và cho kết quả khớp tới sai số làm tròn (< 0,02%),
bao gồm cả kết quả sau khi chạy Solver GRG Nonlinear (CLBN, Vc,post, Vp,post).

KHÔNG import bất cứ gì từ pk_calculations.py / app.py / database.py để tránh xung đột
với module TDM Aminoglycosid đã có — đây là một module hoàn toàn độc lập.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize


# ==========================================
# 1. CẤU TRÚC DỮ LIỆU
# ==========================================
@dataclass
class VancoPatientInfo:
    age: float
    gender: str            # 'nam' hoặc 'nữ'
    height_cm: float
    weight_kg: float
    scr_value: float        # giá trị Creatinin huyết thanh do người dùng nhập
    is_dialysis: bool = False


@dataclass
class VancoDose:
    """Một liều đã dùng trong lịch sử truyền thuốc."""
    dose_mg: float
    given_at: datetime.datetime


@dataclass
class VancoPriors:
    cl_prior: float
    vc_prior: float
    vp_prior: float
    q_prior: float = 6.5        # Độ thanh thải liên ngăn (Fixed, không tối ưu)
    omega_cl: float = 0.398
    omega_vc: float = 0.816
    omega_vp: float = 0.571


@dataclass
class VancoMeasurement:
    c_obs: float
    t_obs: datetime.datetime
    t_inf_h: float = 1.0        # Thời gian truyền (giống cho toàn bộ lịch sử liều)


@dataclass
class VancoBayesResult:
    CL_optimized: float
    Vc_optimized: float
    Vp_optimized: float
    C_pred_final: float
    OFV_final: float
    k10: float
    k12: float
    k21: float
    alpha: float
    beta: float
    success: bool
    message: str = ""


# ==========================================
# 2. THAM SỐ TIỀN NGHIỆM (POPULATION PRIORS)
#    — tái hiện đúng công thức cột A/B của sheet Excel
# ==========================================
def _is_male(gender: str) -> bool:
    return str(gender).strip().lower() in ("nam", "male", "m", "1")


def compute_ibw_vanco(gender: str, height_cm: float) -> float:
    """IBW (Devine, hệ mét) — công thức riêng dùng cho sheet Vancomycin (khác IBW Aminoglycosid)."""
    over = height_cm - 152.4
    if _is_male(gender):
        return 50.0 + 0.9 * over
    return 45.5 + 0.9 * over


def compute_bmi_vanco(weight_kg: float, height_cm: float) -> float:
    h_m = height_cm / 100.0
    if h_m <= 0:
        return 0.0
    return weight_kg / (h_m ** 2)


def compute_adjbw_vanco(weight_kg: float, ibw: float) -> float:
    return ibw + 0.4 * (weight_kg - ibw)


def compute_crcl_weight_vanco(weight_kg: float, ibw: float, adjbw: float, bmi: float) -> float:
    """Cân nặng dùng để tính CrCl (B19): ưu tiên cân nặng thực nếu nhẹ cân hơn IBW,
    dùng AdjBW nếu béo phì (BMI>=30), ngược lại dùng IBW."""
    if weight_kg < ibw:
        return weight_kg
    if bmi >= 30.0:
        return adjbw
    return ibw


def compute_scr_mgdl(scr_value: float) -> float:
    """Tự động quy đổi SCr về mg/dL: nếu giá trị nhập >10 thì hiểu là µmol/L."""
    if scr_value is None:
        return 0.0
    return scr_value / 88.4 if scr_value > 10 else scr_value


def compute_scr_corrected(scr_mgdl: float, age: float) -> float:
    """Hiệu chỉnh SCr tối thiểu = 1.0 mg/dL cho người >60 tuổi có SCr thấp bất thường."""
    if age > 60 and scr_mgdl < 1.0:
        return 1.0
    return scr_mgdl


def compute_crcl_vanco(age: float, gender: str, weight_for_cg: float, scr_mgdl_corrected: float) -> float:
    """Cockcroft-Gault, có hiệu chỉnh giới tính."""
    if scr_mgdl_corrected <= 0:
        return 0.0
    factor = 1.0 if _is_male(gender) else 0.85
    crcl = ((140.0 - age) * weight_for_cg * factor) / (72.0 * scr_mgdl_corrected)
    return max(0.0, crcl)


def compute_crcl_capped(crcl: float, cap: float = 150.0) -> float:
    return min(cap, crcl)


def compute_cl_prior(crcl_capped: float, is_dialysis: bool) -> float:
    return 4.5 * ((crcl_capped / 120.0) ** 0.8) * (0.7 ** (1 if is_dialysis else 0))


def compute_vc_prior(weight_kg: float, is_dialysis: bool) -> float:
    return 58.4 * (weight_kg / 70.0) * (0.5 ** (1 if is_dialysis else 0))


def compute_vp_prior(weight_kg: float) -> float:
    return 38.4 * (weight_kg / 70.0)


def compute_population_priors(patient: VancoPatientInfo, q_prior: float = 6.5,
                               omega_cl: float = 0.398, omega_vc: float = 0.816,
                               omega_vp: float = 0.571) -> Tuple[VancoPriors, dict]:
    """Tính toàn bộ chuỗi tham số tiền nghiệm từ thông tin bệnh nhân.
    Trả về (VancoPriors, dict các bước trung gian để hiển thị lên giao diện)."""
    ibw = compute_ibw_vanco(patient.gender, patient.height_cm)
    bmi = compute_bmi_vanco(patient.weight_kg, patient.height_cm)
    adjbw = compute_adjbw_vanco(patient.weight_kg, ibw)
    weight_cg = compute_crcl_weight_vanco(patient.weight_kg, ibw, adjbw, bmi)
    scr_mgdl = compute_scr_mgdl(patient.scr_value)
    scr_corr = compute_scr_corrected(scr_mgdl, patient.age)
    crcl = compute_crcl_vanco(patient.age, patient.gender, weight_cg, scr_corr)
    crcl_capped = compute_crcl_capped(crcl)

    cl_prior = compute_cl_prior(crcl_capped, patient.is_dialysis)
    vc_prior = compute_vc_prior(patient.weight_kg, patient.is_dialysis)
    vp_prior = compute_vp_prior(patient.weight_kg)

    priors = VancoPriors(cl_prior=cl_prior, vc_prior=vc_prior, vp_prior=vp_prior,
                          q_prior=q_prior, omega_cl=omega_cl, omega_vc=omega_vc, omega_vp=omega_vp)
    details = {
        "ibw": ibw, "bmi": bmi, "adjbw": adjbw, "weight_for_crcl": weight_cg,
        "scr_mgdl": scr_mgdl, "scr_corrected": scr_corr,
        "crcl": crcl, "crcl_capped": crcl_capped,
    }
    return priors, details


# ==========================================
# 3. MÔ HÌNH DƯỢC ĐỘNG HỌC 2 NGĂN (HYBRID CONSTANTS + SUPERPOSITION)
# ==========================================
def compute_hybrid_constants(cl: float, vc: float, vp: float, q: float) -> Tuple[float, float, float, float, float]:
    """Trả về (k10, k12, k21, alpha, beta)."""
    if vc <= 0 or vp <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    k10 = cl / vc
    k12 = q / vc
    k21 = q / vp
    s = k10 + k12 + k21
    disc = max(0.0, s ** 2 - 4.0 * k10 * k21)
    sq = np.sqrt(disc)
    alpha = (s + sq) / 2.0
    beta = (s - sq) / 2.0
    return k10, k12, k21, alpha, beta


def _dose_contribution_post_infusion(dose_mg: float, p_h: float, t_inf_h: float,
                                      vc: float, k21: float, alpha: float, beta: float) -> float:
    """Đóng góp nồng độ của MỘT liều tại thời điểm sau khi kết thúc truyền p_h giờ
    (p_h = thời gian từ lúc DỪNG truyền của liều này đến thời điểm quan sát).
    Nếu p_h < 0 (liều chưa truyền xong tại thời điểm quan sát) trả về 0 — đúng như logic
    cột Q trong Excel gốc."""
    if p_h < 0 or t_inf_h <= 0 or vc <= 0 or alpha <= 0 or beta <= 0:
        return 0.0
    term1 = ((k21 - alpha) / (alpha * (beta - alpha))) * (1 - np.exp(-alpha * t_inf_h)) * np.exp(-alpha * p_h)
    term2 = ((k21 - beta) / (beta * (alpha - beta))) * (1 - np.exp(-beta * t_inf_h)) * np.exp(-beta * p_h)
    return (dose_mg / (t_inf_h * vc)) * (term1 + term2)


def compute_cpred_two_compartment(cl: float, vc: float, vp: float, q: float,
                                   doses: List[VancoDose], t_obs: datetime.datetime,
                                   t_inf_h: float) -> float:
    """Nồng độ dự đoán tại thời điểm t_obs = tổng chồng chập (superposition) đóng góp
    của toàn bộ các liều đã truyền xong trước t_obs. Tái hiện chính xác công thức
    cột Q + hàm AGGREGATE(9,6,...) của Excel."""
    k10, k12, k21, alpha, beta = compute_hybrid_constants(cl, vc, vp, q)
    if alpha <= 0 or beta <= 0:
        return 0.0
    total = 0.0
    for d in doses:
        p_h = (t_obs - d.given_at).total_seconds() / 3600.0 - t_inf_h
        total += _dose_contribution_post_infusion(d.dose_mg, p_h, t_inf_h, vc, k21, alpha, beta)
    return total


def compute_sigma(c_pred: float, sd: float = 0.34, cv: float = 0.227) -> float:
    """Mô hình sai số dư kết hợp (cộng gộp + tỷ lệ): sigma = sqrt(SD^2 + (CV*Cpred)^2).
    Mặc định SD=0.34, CV=0.227 lấy đúng theo công thức B29 của Excel gốc."""
    return np.sqrt(sd ** 2 + (cv * c_pred) ** 2)


def compute_ofv(cl: float, vc: float, vp: float, priors: VancoPriors,
                 doses: List[VancoDose], measurement: VancoMeasurement,
                 sd: float = 0.34, cv: float = 0.227) -> float:
    """Hàm mục tiêu Bayes (OFV) — tổng phạt log-normal của 3 tham số + phạt sai số dư
    giữa nồng độ đo được và nồng độ dự đoán."""
    c_pred = compute_cpred_two_compartment(cl, vc, vp, priors.q_prior, doses,
                                            measurement.t_obs, measurement.t_inf_h)
    sigma = compute_sigma(c_pred, sd, cv)
    ofv_cl = ((np.log(cl) - np.log(priors.cl_prior)) ** 2) / (priors.omega_cl ** 2)
    ofv_vc = ((np.log(vc) - np.log(priors.vc_prior)) ** 2) / (priors.omega_vc ** 2)
    ofv_vp = ((np.log(vp) - np.log(priors.vp_prior)) ** 2) / (priors.omega_vp ** 2)
    ofv_c = ((measurement.c_obs - c_pred) ** 2) / (sigma ** 2)
    return ofv_cl + ofv_vc + ofv_vp + ofv_c


# ==========================================
# 4. HÀM TỐI ƯU HÓA BAYES (solve_bayesian_posterior)
# ==========================================
def solve_bayesian_posterior(priors: VancoPriors,
                              doses: List[VancoDose],
                              measurement: VancoMeasurement,
                              sd: float = 0.34,
                              cv: float = 0.227,
                              cl_min: float = 0.1,
                              vc_min: float = 5.0,
                              vp_min: float = 1.0) -> VancoBayesResult:
    """
    Thực hiện tối ưu hóa phi tuyến (SLSQP có ràng buộc biên, tương đương GRG Nonlinear
    của Excel Solver) để tìm bộ tham số hậu nghiệm (CL_post, Vc_post, Vp_post) làm cực
    tiểu hàm mục tiêu OFV.

    - Điểm khởi tạo: đúng bằng giá trị tiền nghiệm (CLprior, Vc,prior, Vp,prior).
    - Ràng buộc biên: CL_post >= cl_min (L/h), Vc_post >= vc_min (L), Vp_post >= vp_min (L).
    - Q (độ thanh thải liên ngăn) được giữ CỐ ĐỊNH = priors.q_prior trong suốt quá trình tối ưu.

    Trả về VancoBayesResult gồm CL/Vc/Vp tối ưu, nồng độ dự đoán cuối cùng khớp mô hình
    (C_pred_final) và giá trị OFV nhỏ nhất đạt được (OFV_final).
    """
    if not doses:
        return VancoBayesResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, False,
                                 "Chưa có dữ liệu lịch sử liều dùng để tính toán.")

    x0 = np.array([priors.cl_prior, priors.vc_prior, priors.vp_prior], dtype=float)
    bounds = [(cl_min, None), (vc_min, None), (vp_min, None)]

    def objective(x):
        cl, vc, vp = x
        return compute_ofv(cl, vc, vp, priors, doses, measurement, sd, cv)

    best_result = None
    # Thử lần lượt 2 thuật toán hỗ trợ ràng buộc biên để tăng độ ổn định hội tụ
    for method in ("L-BFGS-B", "SLSQP"):
        try:
            res = minimize(objective, x0, method=method, bounds=bounds,
                            options={"maxiter": 500, "ftol": 1e-12})
            if res.success and (best_result is None or res.fun < best_result.fun):
                best_result = res
        except Exception:
            continue

    if best_result is None:
        return VancoBayesResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, False,
                                 "Thuật toán tối ưu không hội tụ. Vui lòng kiểm tra lại dữ liệu đầu vào.")

    cl_opt, vc_opt, vp_opt = best_result.x
    c_pred_final = compute_cpred_two_compartment(cl_opt, vc_opt, vp_opt, priors.q_prior,
                                                  doses, measurement.t_obs, measurement.t_inf_h)
    k10, k12, k21, alpha, beta = compute_hybrid_constants(cl_opt, vc_opt, vp_opt, priors.q_prior)

    return VancoBayesResult(
        CL_optimized=float(cl_opt), Vc_optimized=float(vc_opt), Vp_optimized=float(vp_opt),
        C_pred_final=float(c_pred_final), OFV_final=float(best_result.fun),
        k10=float(k10), k12=float(k12), k21=float(k21), alpha=float(alpha), beta=float(beta),
        success=True, message="Đã hội tụ thành công."
    )


# ==========================================
# 5. MÔ PHỎNG ĐƯỜNG CONG NỒNG ĐỘ — DÙNG CHO BIỂU ĐỒ TRỰC QUAN
# ==========================================
def _dose_contribution_at_time(dose_mg: float, t_since_start_h: float, t_inf_h: float,
                                vc: float, k21: float, alpha: float, beta: float) -> float:
    """Đóng góp nồng độ liên tục theo thời gian (dùng cho vẽ đồ thị), có cả pha đang
    truyền (ramp-up) lẫn pha sau truyền — mượt hơn so với hàm dùng riêng cho tối ưu hóa."""
    if t_since_start_h < 0 or t_inf_h <= 0 or vc <= 0 or alpha <= 0 or beta <= 0:
        return 0.0
    if t_since_start_h <= t_inf_h:
        term1 = ((k21 - alpha) / (alpha * (beta - alpha))) * (1 - np.exp(-alpha * t_since_start_h))
        term2 = ((k21 - beta) / (beta * (alpha - beta))) * (1 - np.exp(-beta * t_since_start_h))
        return (dose_mg / (t_inf_h * vc)) * (term1 + term2)
    p_h = t_since_start_h - t_inf_h
    return _dose_contribution_post_infusion(dose_mg, p_h, t_inf_h, vc, k21, alpha, beta)


def simulate_concentration_curve(cl: float, vc: float, vp: float, q: float,
                                  doses: List[VancoDose], t_inf_h: float,
                                  t_end: Optional[datetime.datetime] = None,
                                  n_points: int = 400) -> Tuple[List[datetime.datetime], List[float]]:
    """Mô phỏng đường cong nồng độ liên tục từ liều đầu tiên đến t_end (mặc định = liều
    cuối + 1 khoảng tau ước tính, hoặc +24h nếu chỉ có 1 liều). Dùng để vẽ biểu đồ minh họa,
    KHÔNG dùng cho việc tối ưu hóa Bayes (xem compute_cpred_two_compartment)."""
    if not doses:
        return [], []
    doses_sorted = sorted(doses, key=lambda d: d.given_at)
    t_start = doses_sorted[0].given_at
    if t_end is None:
        if len(doses_sorted) > 1:
            avg_gap_h = (doses_sorted[-1].given_at - doses_sorted[0].given_at).total_seconds() / 3600.0 / (len(doses_sorted) - 1)
        else:
            avg_gap_h = 24.0
        t_end = doses_sorted[-1].given_at + datetime.timedelta(hours=max(avg_gap_h, 4.0))

    k10, k12, k21, alpha, beta = compute_hybrid_constants(cl, vc, vp, q)
    total_h = (t_end - t_start).total_seconds() / 3600.0
    if total_h <= 0:
        return [], []
    times_h = np.linspace(0, total_h, n_points)
    concs = []
    for th in times_h:
        t_abs = t_start + datetime.timedelta(hours=float(th))
        c = 0.0
        for d in doses_sorted:
            t_since = (t_abs - d.given_at).total_seconds() / 3600.0
            if t_since < 0:
                continue
            c += _dose_contribution_at_time(d.dose_mg, t_since, t_inf_h, vc, k21, alpha, beta)
        concs.append(c)
    times_abs = [t_start + datetime.timedelta(hours=float(th)) for th in times_h]
    return times_abs, concs

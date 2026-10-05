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
from scipy.linalg import expm











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
    points: list = field(default_factory=list)  # [{"t_obs","c_obs","c_pred","ofv"}] mỗi điểm đo
    anchor_dose: object = None  # VancoDose "đang dùng" (liều kề trước các điểm đo của block này)











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
    # LUU Y DON VI: patient.scr_value phai DA o dang mg/dL (UI luon quy doi truoc theo don
    # vi nguoi dung chon tuong minh) -- KHONG con goi lai compute_scr_mgdl() (tu doan >10) o
    # day nua, tranh chia 88.4 lan 2 doi voi benh nhan SCr thuc te > 10 mg/dL (suy than nang).
    scr_mgdl = patient.scr_value
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











# Sai so du Goti 2018 -- Bang 2 bai goc: "Additive Error SD 3.4 mg/L", "Proportional error 22.7 %CV".
# SUA LOI (2026-10): truoc day dung 0.34 (theo Excel, lech 10 lan so voi bai bao).
GOTI_RES_ERR_ADD = 3.4
GOTI_RES_ERR_PROP = 0.227


def compute_sigma(c_pred: float, sd: float = GOTI_RES_ERR_ADD, cv: float = GOTI_RES_ERR_PROP) -> float:



    """Mô hình sai số dư kết hợp (cộng gộp + tỷ lệ): sigma = sqrt(SD^2 + (CV*Cpred)^2).



    Mặc định SD=3.4 mg/L, CV=0.227 theo Bảng 2 bài Goti 2018 (trước đây 0.34 theo Excel — lệch 10 lần)."""



    return np.sqrt(sd ** 2 + (cv * c_pred) ** 2)











def _cl_segments_for_solve(cl: float, doses: List[VancoDose],
                            historical_cl_segments, current_segment_start) -> List[Tuple[datetime.datetime, float]]:
    """Ghép các đoạn CL đã CỐ ĐỊNH từ những lần TDM trước (historical_cl_segments) với đoạn
    HIỆN TẠI dùng "cl" (giá trị đang được tối ưu), bắt đầu từ current_segment_start. Nếu
    không có lịch sử (historical_cl_segments rỗng/None), chỉ có 1 đoạn duy nhất — tương
    đương hoàn toàn CL không đổi suốt lịch sử liều (hành vi gốc, đã kiểm định khớp tuyệt
    đối với compute_cpred_two_compartment())."""
    seg_start = current_segment_start if current_segment_start is not None else min(d.given_at for d in doses)
    return list(historical_cl_segments or []) + [(seg_start, cl)]


def compute_ofv(cl: float, vc: float, vp: float, priors: VancoPriors,
                 doses: List[VancoDose], measurements: List[VancoMeasurement],
                 sd: float = GOTI_RES_ERR_ADD, cv: float = GOTI_RES_ERR_PROP,
                 historical_cl_segments: Optional[List[Tuple[datetime.datetime, float]]] = None,
                 current_segment_start: Optional[datetime.datetime] = None) -> float:
    """Hàm mục tiêu Bayes (OFV) — tổng phạt log-normal của 3 tham số + tổng phạt sai số dư
    của TỪNG điểm đo (hỗ trợ nhiều điểm đo Cobs/Tobs cùng lúc):
        OFV_tổng = OFV_CL + OFV_Vc + OFV_Vp + Σ_i (Cobs_i - Cpred_i)^2 / sigma_i^2
    (measurements có thể chỉ gồm 1 điểm — khi đó tương đương công thức gốc).

    historical_cl_segments/current_segment_start: hỗ trợ CL BẬC THANG THEO THỜI GIAN (xử lý
    AKI/suy thận cấp) — xem _cl_segments_for_solve(). Mặc định None => hành vi gốc, CL không
    đổi suốt lịch sử liều (tương thích ngược 100%, đã kiểm định)."""
    ofv_cl = ((np.log(cl) - np.log(priors.cl_prior)) ** 2) / (priors.omega_cl ** 2)
    ofv_vc = ((np.log(vc) - np.log(priors.vc_prior)) ** 2) / (priors.omega_vc ** 2)
    ofv_vp = ((np.log(vp) - np.log(priors.vp_prior)) ** 2) / (priors.omega_vp ** 2)
    cl_segments = _cl_segments_for_solve(cl, doses, historical_cl_segments, current_segment_start)
    ofv_points = 0.0
    for m in measurements:
        c_pred = compute_cpred_two_compartment_piecewise(cl_segments, vc, vp, priors.q_prior, doses, m.t_obs, m.t_inf_h)
        sigma = compute_sigma(c_pred, sd, cv)
        ofv_points += ((m.c_obs - c_pred) ** 2) / (sigma ** 2)
    return ofv_cl + ofv_vc + ofv_vp + ofv_points











# ==========================================



# 4. HÀM TỐI ƯU HÓA BAYES (solve_bayesian_posterior)



# ==========================================



def solve_bayesian_posterior(priors: VancoPriors,
                              doses: List[VancoDose],
                              measurements,
                              sd: float = GOTI_RES_ERR_ADD,
                              cv: float = GOTI_RES_ERR_PROP,
                              cl_min: float = 0.1,
                              vc_min: float = 5.0,
                              vp_min: float = 1.0,
                              historical_cl_segments: Optional[List[Tuple[datetime.datetime, float]]] = None,
                              current_segment_start: Optional[datetime.datetime] = None) -> VancoBayesResult:



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



    measurements = [measurements] if isinstance(measurements, VancoMeasurement) else list(measurements)
    if not doses:
        return VancoBayesResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, False,
                                 "Chưa có dữ liệu lịch sử liều dùng để tính toán.")
    if not measurements:
        return VancoBayesResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, False,
                                 "Chưa có điểm đo Cobs/Tobs nào để tính toán.")

    x0 = np.array([priors.cl_prior, priors.vc_prior, priors.vp_prior], dtype=float)
    bounds = [(cl_min, None), (vc_min, None), (vp_min, None)]

    def objective(x):
        cl, vc, vp = x
        return compute_ofv(cl, vc, vp, priors, doses, measurements, sd, cv,
                            historical_cl_segments, current_segment_start)







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
    k10, k12, k21, alpha, beta = compute_hybrid_constants(cl_opt, vc_opt, vp_opt, priors.q_prior)

    # Cpred + OFV riêng cho TỪNG điểm đo (yêu cầu #3) — sắp theo thời gian đo tăng dần
    measurements_sorted = sorted(measurements, key=lambda m: m.t_obs)
    cl_segments_final = _cl_segments_for_solve(cl_opt, doses, historical_cl_segments, current_segment_start)
    points = []
    for m in measurements_sorted:
        c_pred_i = compute_cpred_two_compartment_piecewise(cl_segments_final, vc_opt, vp_opt, priors.q_prior,
                                                             doses, m.t_obs, m.t_inf_h)
        sigma_i = compute_sigma(c_pred_i, sd, cv)
        ofv_i = ((m.c_obs - c_pred_i) ** 2) / (sigma_i ** 2)
        points.append({"t_obs": m.t_obs, "c_obs": m.c_obs, "c_pred": float(c_pred_i), "ofv": float(ofv_i)})
    c_pred_final = points[-1]["c_pred"] if points else 0.0  # Cpred tại điểm đo gần nhất (để tương thích hiển thị cũ)

    return VancoBayesResult(
        CL_optimized=float(cl_opt), Vc_optimized=float(vc_opt), Vp_optimized=float(vp_opt),
        C_pred_final=float(c_pred_final), OFV_final=float(best_result.fun),
        k10=float(k10), k12=float(k12), k21=float(k21), alpha=float(alpha), beta=float(beta),
        success=True, message="Đã hội tụ thành công.", points=points
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





# ==========================================
# 6. PHUONG PHAP COLLIN 2019 (mo hinh hiep bien: PMA/tuoi, can nang, SCr,
#    benh mau ac tinh - STDY10, mau lay got chan - STDY13)
#    -- tai hien dung cong thuc sheet Excel "collin Bayes"
#
#    LUU Y QUAN TRONG: vung A16:B23 cua sheet Excel goc (SCr hieu chinh, IBW,
#    BMI, AdjBW, Can nang uoc tinh CrCl, CrCl, CrCl capped) KHONG duoc dung
#    trong bat ky cong thuc tien nghiem nao cua Collin -- sheet Excel chi giu
#    lai vung nay de hien thi song song, doi chieu truc quan voi sheet Goti.
#    Vi vay cac ham tinh tien nghiem Collin duoi day KHONG dung CrCl/IBW/BMI.
#    (Tab giao dien van co the goi lai cac ham compute_ibw_vanco/compute_bmi_vanco/
#    compute_crcl_vanco... cua Goti thuan tuy de HIEN THI tham khao cho dong bo
#    giao dien giua 2 phuong phap, nhung gia tri do KHONG duoc dua vao priors.)
# ==========================================

@dataclass
class VancoPatientInfoCollin:
    """Thong tin benh nhan can cho phuong phap Collin 2019 (khac Goti o cho
    khong dung 'is_dialysis' ma dung 2 hiep bien rieng: benh mau ac tinh va
    mau lay got chan)."""
    age: float
    gender: str                    # 'nam' hoac 'nu'
    height_cm: float
    weight_kg: float
    scr_value: float                # SCr do nguoi dung nhap (tu dong quy doi don vi nhu Goti)
    is_malignancy: bool = False     # Benh mau ac tinh (STDY10)
    is_heelprick: bool = False      # Mau lay got chan - Heel-prick sample (STDY13)


# --- Hang so quan the Collin 2019 (co dinh, KHONG cho nguoi dung chinh sua) ---
COLLIN_THETA_CL = 5.31
COLLIN_THETA_V1 = 42.9
COLLIN_THETA_V2 = 41.7
COLLIN_THETA_Q2 = 3.22
COLLIN_PMA50 = 46.4
COLLIN_GAMMA1 = 2.89
COLLIN_AGE50 = 61.6
COLLIN_GAMMA2 = 2.24
COLLIN_THETA_SCR = 0.649
COLLIN_THETA_STDY10 = 294.0 / 1000.0
COLLIN_THETA_STDY13_V1 = 312.0 / 1000.0
COLLIN_THETA_STDY13_Q2 = 597.0 / 1000.0
COLLIN_CV_CL = 27.9
COLLIN_CV_V1 = 27.3
COLLIN_CV_V2 = 97.9
COLLIN_RES_ERR_PROP = 21.5          # % - he so CV ty le cua sai so du (o B57 Excel: *0.215)
COLLIN_RES_ERR_ADD = 1.23           # SD cong gop cua sai so du (o B57 Excel: 1.23^2)

# Sai so du (SD/CV) co dinh cua mo hinh Collin 2019 -- dung khi goi solve_bayesian_posterior()
COLLIN_SD = COLLIN_RES_ERR_ADD              # 1.23
COLLIN_CV = COLLIN_RES_ERR_PROP / 100.0     # 0.215


COLLIN_WEEKS_PER_YEAR = 52.1429


def compute_pma_weeks_collin(age: float) -> float:
    """PMA (tuan) = Tuoi (nam) * 52.1429 + 40 tuan.
    SUA (2026-10) theo bai goc Collin 2019 (muc 2.1): "Postmenstrual age for patients other than
    neonates was assumed to be 40 weeks longer than the recorded postnatal age". Excel goc chi
    dung tuoi*52.1429 (thieu 40 tuan) -- khong anh huong dang ke voi nguoi lon (~0.8 nam)
    nhung can thiet cho tre em. Luu y: giao dien chi nhap TUOI (khong co tuoi thai) nen sinh
    non (preterm) chua duoc mo hinh hoa dung."""
    return age * COLLIN_WEEKS_PER_YEAR + 40.0


def compute_f_size_collin(weight_kg: float) -> float:
    """He so kich thuoc theo can nang -- B44 = Can nang / 70."""
    return weight_kg / 70.0


def compute_f_mat_collin(pma_weeks: float, pma50: float = COLLIN_PMA50,
                          gamma1: float = COLLIN_GAMMA1) -> float:
    """He so truong thanh (maturation) theo PMA -- ham Hill, tai hien B45."""
    if pma_weeks <= 0:
        return 0.0
    return (pma_weeks ** gamma1) / (pma_weeks ** gamma1 + pma50 ** gamma1)


def compute_f_decline_collin(pma_years: float, age50: float = COLLIN_AGE50,
                              gamma2: float = COLLIN_GAMMA2) -> float:
    """He so suy giam chuc nang than theo TUOI -- Phuong trinh 12 bai goc Collin 2019:
        F_decline = PMA(yr)^-g2 / (PMA(yr)^-g2 + AGE50^-g2)
    SUA LOI (2026-10): ban truoc dung CAN NANG (chep nguyen o B46 cua Excel goc -- Excel sai so
    voi bai bao). Da kiem dinh: cong thuc nay tai hien dung cac vi du in trong bai
    (35 tuoi/70 kg/SCr 0.83 -> CL 4.10 L/h; 60 tuoi/65 kg/SCr 0.97 -> 2.55 L/h)."""
    if pma_years <= 0:
        return 0.0
    return (pma_years ** -gamma2) / (pma_years ** -gamma2 + age50 ** -gamma2)


def compute_scr_std_collin(age: float) -> float:
    """SCR chuan hoa theo tuoi -- tai hien cong thuc B47."""
    pma_years = compute_pma_weeks_collin(age) / COLLIN_WEEKS_PER_YEAR   # Phuong trinh 5 dung PMA (nam)
    if pma_years <= 0:
        return 0.0
    return float(np.exp(-1.228 + np.log10(pma_years) * 0.672 + 6.27 * np.exp(-3.11 * pma_years)))


def compute_f_scr_collin(scr_mgdl: float, age: float, theta_scr: float = COLLIN_THETA_SCR) -> float:
    """He so hieu chinh theo SCr -- tai hien cong thuc B48. LUU Y: dung SCr THO
    (chua hieu chinh toi thieu 1.0 mg/dL cho nguoi >60 tuoi nhu ben Goti), dung
    dung nhu Excel goc dung B6 (khong dung B17 da hieu chinh)."""
    scr_std = compute_scr_std_collin(age)
    return float(np.exp(-theta_scr * (scr_mgdl - scr_std)))


def compute_v1_prior_collin(weight_kg: float, is_heelprick: bool,
                             theta_v1: float = COLLIN_THETA_V1,
                             theta_stdy13_v1: float = COLLIN_THETA_STDY13_V1) -> float:
    """V1_prior (Vc) -- tai hien cong thuc B49."""
    f_size = compute_f_size_collin(weight_kg)
    return theta_v1 * f_size * (1.0 - (1 if is_heelprick else 0) * theta_stdy13_v1)


def compute_v2_prior_collin(weight_kg: float, theta_v2: float = COLLIN_THETA_V2) -> float:
    """V2_prior (Vp) -- tai hien cong thuc B50."""
    return theta_v2 * compute_f_size_collin(weight_kg)


def compute_cl_prior_collin(v1_prior: float, f_mat: float, f_decline: float, f_scr: float,
                             is_malignancy: bool, theta_cl: float = COLLIN_THETA_CL,
                             theta_v1: float = COLLIN_THETA_V1,
                             theta_stdy10: float = COLLIN_THETA_STDY10) -> float:
    """CL_prior -- tai hien cong thuc B51."""
    return (theta_cl * ((v1_prior / theta_v1) ** 0.75) * f_mat * f_decline * f_scr *
            (1.0 + (1 if is_malignancy else 0) * theta_stdy10))


def compute_q2_prior_collin(v2_prior: float, is_heelprick: bool,
                             theta_q2: float = COLLIN_THETA_Q2,
                             theta_v2: float = COLLIN_THETA_V2,
                             theta_stdy13_q2: float = COLLIN_THETA_STDY13_Q2) -> float:
    """Q2_prior (do thanh thai lien ngan tien nghiem) -- tai hien cong thuc B52.
    Khac Goti (Q co dinh = 6.5), Collin tinh Q2_prior theo hiep bien benh nhan,
    nhung van duoc GIU CO DINH trong qua trinh toi uu Bayes (giong het co che
    cua Q trong Goti) -- KHONG can sua solve_bayesian_posterior()."""
    return theta_q2 * ((v2_prior / theta_v2) ** 0.75) * (1.0 - (1 if is_heelprick else 0) * theta_stdy13_q2)


def compute_omega_from_cv(cv_percent: float) -> float:
    """Quy doi CV% (variability quan the) sang omega = SD cua log-normal.
    Tai hien cong thuc cot D53:D56 cua Excel: omega = sqrt(ln(1 + (CV/100)^2))."""
    cv = cv_percent / 100.0
    return float(np.sqrt(np.log(1.0 + cv ** 2)))


def compute_population_priors_collin(patient: VancoPatientInfoCollin) -> Tuple[VancoPriors, dict]:
    """Tinh toan bo chuoi tham so tien nghiem theo phuong phap Collin 2019 tu
    thong tin benh nhan. Tra ve (VancoPriors, dict cac buoc trung gian de hien
    thi len giao dien). VancoPriors tra ve co cung cau truc voi Goti (cl_prior,
    vc_prior=V1, vp_prior=V2, q_prior=Q2, omega_cl/vc/vp) nen tuong thich hoan
    toan voi compute_cpred_two_compartment / compute_ofv / solve_bayesian_posterior
    hien co -- khong can sua bat ky ham toi uu hoa Bayes nao."""
    # LUU Y DON VI: patient.scr_value phai DA o dang mg/dL (xem ghi chu chi tiet trong
    # compute_population_priors() o tren) -- khong con tu doan don vi theo nguong >10 nua.
    scr_mgdl = patient.scr_value

    pma_weeks = compute_pma_weeks_collin(patient.age)
    f_size = compute_f_size_collin(patient.weight_kg)
    f_mat = compute_f_mat_collin(pma_weeks)
    f_decline = compute_f_decline_collin(pma_weeks / COLLIN_WEEKS_PER_YEAR)
    f_scr = compute_f_scr_collin(scr_mgdl, patient.age)

    v1_prior = compute_v1_prior_collin(patient.weight_kg, patient.is_heelprick)
    v2_prior = compute_v2_prior_collin(patient.weight_kg)
    cl_prior = compute_cl_prior_collin(v1_prior, f_mat, f_decline, f_scr, patient.is_malignancy)
    q2_prior = compute_q2_prior_collin(v2_prior, patient.is_heelprick)

    omega_cl = compute_omega_from_cv(COLLIN_CV_CL)
    omega_vc = compute_omega_from_cv(COLLIN_CV_V1)
    omega_vp = compute_omega_from_cv(COLLIN_CV_V2)

    priors = VancoPriors(cl_prior=cl_prior, vc_prior=v1_prior, vp_prior=v2_prior,
                          q_prior=q2_prior, omega_cl=omega_cl, omega_vc=omega_vc, omega_vp=omega_vp)

    details = {
        "scr_mgdl": scr_mgdl, "pma_weeks": pma_weeks, "f_size": f_size,
        "f_mat": f_mat, "f_decline": f_decline, "f_scr": f_scr,
        "v1_prior": v1_prior, "v2_prior": v2_prior, "q2_prior": q2_prior,
    }
    return priors, details


# ==========================================
# 7. NHIỀU ĐIỂM ĐO / NHIỀU LẦN TDM (Sequential Bayesian forecasting theo occasion)
#    — nhóm các điểm đo theo "khoảng đưa liều" (tau) đang hiệu lực tại thời điểm đo,
#    rồi chạy tối ưu Bayes TUẦN TỰ qua từng khoảng: khoảng sau dùng Vc/Vp/Q hậu nghiệm
#    của khoảng trước làm tiền nghiệm, riêng CL được tính lại từ SCr gần nhất với Tobs
#    của khoảng đó theo đúng mô hình quần thể (Goti 2018 hoặc Collin 2019) đang chọn.
# ==========================================

def find_nearest_scr(scr_entries, t_obs):
    """scr_entries: list các (scr_value, thời_điểm_đo). Trả về scr_value của bản ghi có
    thời điểm đo GẦN t_obs NHẤT (chênh lệch tuyệt đối nhỏ nhất). None nếu rỗng."""
    if not scr_entries:
        return None
    return min(scr_entries, key=lambda e: abs((e[1] - t_obs).total_seconds()))[0]


def find_nearest_scr_entry(scr_entries, t_obs):
    """Giống find_nearest_scr() nhưng trả về CẢ CẶP (scr_value, thời_điểm_đo) thay vì chỉ
    giá trị — dùng làm mốc ranh giới đoạn CL bậc thang (xem build_cl_segments_vanco() và
    solve_bayesian_sequential()). None nếu rỗng."""
    if not scr_entries:
        return None
    return min(scr_entries, key=lambda e: abs((e[1] - t_obs).total_seconds()))


def recompute_cl_prior_goti(patient: VancoPatientInfo, scr_value: float) -> float:
    """Tính lại CL_prior theo mô hình Goti 2018 nhưng dùng một giá trị SCr KHÁC (của lần
    đo gần với Tobs của một khoảng đưa liều cụ thể) — các hiệp biến còn lại (tuổi, giới
    tính, cân nặng, lọc máu) giữ nguyên theo thông tin bệnh nhân."""
    ibw = compute_ibw_vanco(patient.gender, patient.height_cm)
    bmi = compute_bmi_vanco(patient.weight_kg, patient.height_cm)
    adjbw = compute_adjbw_vanco(patient.weight_kg, ibw)
    weight_cg = compute_crcl_weight_vanco(patient.weight_kg, ibw, adjbw, bmi)
    scr_mgdl = scr_value  # da o dang mg/dL, xem ghi chu don vi trong compute_population_priors()
    scr_corr = compute_scr_corrected(scr_mgdl, patient.age)
    crcl = compute_crcl_vanco(patient.age, patient.gender, weight_cg, scr_corr)
    crcl_capped = compute_crcl_capped(crcl)
    return compute_cl_prior(crcl_capped, patient.is_dialysis)


def recompute_cl_prior_collin(patient: VancoPatientInfoCollin, scr_value: float) -> float:
    """Tương tự recompute_cl_prior_goti() nhưng theo mô hình Collin 2019."""
    pma_weeks = compute_pma_weeks_collin(patient.age)
    f_mat = compute_f_mat_collin(pma_weeks)
    f_decline = compute_f_decline_collin(pma_weeks / COLLIN_WEEKS_PER_YEAR)
    v1_prior = compute_v1_prior_collin(patient.weight_kg, patient.is_heelprick)
    scr_mgdl = scr_value  # da o dang mg/dL, xem ghi chu don vi trong compute_population_priors()
    f_scr = compute_f_scr_collin(scr_mgdl, patient.age)
    return compute_cl_prior_collin(v1_prior, f_mat, f_decline, f_scr, patient.is_malignancy)


def group_measurements_by_dose_block(measurements: List[VancoMeasurement], doses: List[VancoDose]):
    """Gom các điểm đo (Cobs/Tobs) theo 'khoảng đưa liều' (tau) đang hiệu lực tại Tobs.
    Với mỗi điểm đo, 'liều neo' (anchor dose) = liều có given_at MUỘN NHẤT nhưng <= Tobs.
    Các điểm đo có cùng liều neo được coi là CÙNG khoảng đưa liều -> gom vào 1 block, chạy
    OFV chung 1 lần (đúng yêu cầu #4). Trả về (blocks, orphans):
      - blocks: list các dict {"anchor_dose": VancoDose, "measurements": [...]},
                đã sắp xếp theo thời gian liều neo tăng dần (occasion 1 -> N).
      - orphans: các điểm đo có Tobs xảy ra TRƯỚC liều đầu tiên (không xác định được liều
                 neo) -> không đủ dữ liệu để tính, bị loại khỏi blocks."""
    doses_sorted = sorted(doses, key=lambda d: d.given_at)
    grouped = {}
    orphans = []
    for m in measurements:
        anchor = None
        for d in doses_sorted:
            if d.given_at <= m.t_obs:
                anchor = d
            else:
                break
        if anchor is None:
            orphans.append(m)
            continue
        grouped.setdefault(anchor.given_at, {"anchor_dose": anchor, "measurements": []})
        grouped[anchor.given_at]["measurements"].append(m)
    blocks = [grouped[k] for k in sorted(grouped.keys())]
    for b in blocks:
        b["measurements"].sort(key=lambda m: m.t_obs)
    return blocks, orphans


def recompute_full_priors_goti(patient: VancoPatientInfo, scr_value: float, q_prior: float = 6.5,
                                omega_cl: float = 0.398, omega_vc: float = 0.816,
                                omega_vp: float = 0.571) -> VancoPriors:
    """Tính lại TOÀN BỘ tiền nghiệm (CL/Vc/Vp/Q) theo mô hình Goti 2018 từ 1 giá trị SCr cụ
    thể (mg/dL, của lần đo gần Tobs của 1 khoảng đưa liều cụ thể) — dùng cho MỌI lần TDM
    (kể cả lần đầu), KHÔNG kế thừa hậu nghiệm của lần TDM trước. Việc này tránh hiện tượng
    Vc/Vp "trôi dạt" dần ra khỏi quần thể tham khảo qua nhiều lần TDM liên tiếp — vì lý do:
    omega (ωVc, ωVp) đo độ biến thiên GIỮA CÁC BỆNH NHÂN so với quần thể, không phải độ tin
    cậy của 1 ước lượng hậu nghiệm từ dữ liệu thưa (thường chỉ 1 mẫu đáy) của lần trước; nếu
    kế thừa hậu nghiệm làm tiền nghiệm mới mà vẫn dùng omega quần thể gốc, sai lệch ngẫu
    nhiên của 1 lần đo sẽ neo lại vĩnh viễn qua các lần sau."""
    patient_i = VancoPatientInfo(age=patient.age, gender=patient.gender, height_cm=patient.height_cm,
                                  weight_kg=patient.weight_kg, scr_value=scr_value, is_dialysis=patient.is_dialysis)
    priors, _ = compute_population_priors(patient_i, q_prior=q_prior, omega_cl=omega_cl,
                                           omega_vc=omega_vc, omega_vp=omega_vp)
    return priors


def recompute_full_priors_collin(patient: VancoPatientInfoCollin, scr_value: float) -> VancoPriors:
    """Tương tự recompute_full_priors_goti() nhưng theo mô hình Collin 2019 — xem giải
    thích chi tiết trong docstring của recompute_full_priors_goti()."""
    patient_i = VancoPatientInfoCollin(age=patient.age, gender=patient.gender, height_cm=patient.height_cm,
                                        weight_kg=patient.weight_kg, scr_value=scr_value,
                                        is_malignancy=patient.is_malignancy, is_heelprick=patient.is_heelprick)
    priors, _ = compute_population_priors_collin(patient_i)
    return priors


def solve_bayesian_sequential(doses: List[VancoDose], blocks: list, recompute_priors_fn,
                               nearest_scr_entry_fn, sd: float = GOTI_RES_ERR_ADD, cv: float = GOTI_RES_ERR_PROP):
    """Chạy tối ưu Bayes qua từng block (mỗi block = 1 khoảng đưa liều, có thể gồm nhiều
    điểm đo cùng lúc).

    (1) Tiền nghiệm: MỌI block (kể cả block đầu) dùng tiền nghiệm CL/Vc/Vp/Q TÍNH LẠI HOÀN
    TOÀN MỚI từ mô hình quần thể (recompute_priors_fn), với SCr gần Tobs của chính block đó —
    không kế thừa Vc/Vp hậu nghiệm của block trước (tránh trôi dạt khỏi quần thể gốc).

    (2) Cpred với CL BẬC THANG (xử lý AKI): CL_post của lần TDM k là CL của KHOẢNG THỜI GIAN
    TỪ lần TDM k-1 ĐẾN lần TDM k (lần 1: từ liều đầu tiên đến TDM 1). Khi giải block k, các
    đoạn trước dùng CL_post CỐ ĐỊNH đã ước lượng; chỉ đoạn (TDM k-1, TDM k] dùng CL đang tối
    ưu. Ranh giới đoạn = thời điểm đo của lần TDM trước (KHÔNG phải thời điểm lấy SCr — vì
    SCr thường lấy cùng lúc mẫu đáy, nếu lấy làm ranh giới thì đoạn hiện tại có độ dài 0 và
    Cobs không còn tham gia ước lượng CL).

    nearest_scr_entry_fn(t_obs) -> (scr_value, thời_điểm_đo); chỉ dùng scr_value để tính CL_prior.
    Trả về list VancoBayesResult (1 phần tử/block); phần tử CUỐI là kết quả hiển thị/lưu."""
    results = []
    seg_start = min(d.given_at for d in doses)
    historical_segments: List[Tuple[datetime.datetime, float]] = []
    for block in blocks:
        scr_i, _ = nearest_scr_entry_fn(block["measurements"][0].t_obs)
        priors_i = recompute_priors_fn(scr_i)
        res = solve_bayesian_posterior(priors_i, doses, block["measurements"], sd=sd, cv=cv,
                                        historical_cl_segments=historical_segments,
                                        current_segment_start=seg_start)
        res.anchor_dose = block["anchor_dose"]
        results.append(res)
        if not res.success:
            break  # Block lỗi -> dừng chuỗi, không cố tính tiếp các block sau
        historical_segments = historical_segments + [(seg_start, res.CL_optimized)]
        seg_start = max(m.t_obs for m in block["measurements"])
    return results

def _segment_transition_2c(a1_0: float, a2_0: float, cl: float, vc: float, vp: float, q: float,
                            rate_mg_per_h: float, dt_h: float) -> Tuple[float, float]:
    """Chuyển trạng thái (A1, A2) — lượng thuốc trong ngăn trung tâm/ngoại vi — qua 1
    khoảng thời gian dt_h, với CL/Vc/Vp/Q CỐ ĐỊNH trong khoảng đó và tốc độ truyền dịch
    rate_mg_per_h KHÔNG ĐỔI trong suốt dt_h (0 nếu không có liều nào đang truyền).

    Dùng công thức "zero-order hold" — nghiệm ĐÓNG (không xấp xỉ số) của hệ tuyến tính
    dX/dt = M·X + B·rate:  X(t+dt) = e^(M·dt)·X(t) + M⁻¹·(e^(M·dt) − I)·(B·rate).
    Đã kiểm định: khớp compute_cpred_two_compartment() tới sai số ~1e-14 khi CL không đổi,
    và khớp lời giải ODE (scipy.integrate.solve_ivp) tới ~1e-9 khi CL đổi bậc thang (AKI)."""
    k10, k12, k21 = cl / vc, q / vc, q / vp
    m = np.array([[-(k10 + k12), k21], [k12, -k21]])
    x0 = np.array([a1_0, a2_0], dtype=float)
    e = expm(m * dt_h)
    if rate_mg_per_h:
        b = np.array([rate_mg_per_h, 0.0])
        x1 = e @ x0 + np.linalg.solve(m, (e - np.eye(2)) @ b)
    else:
        x1 = e @ x0
    return float(x1[0]), float(x1[1])


def compute_cpred_two_compartment_piecewise(cl_segments: List[Tuple[datetime.datetime, float]],
                                             vc: float, vp: float, q: float,
                                             doses: List[VancoDose], t_obs: datetime.datetime,
                                             t_inf_h: float) -> float:
    """Nồng độ dự đoán tại t_obs khi CL THAY ĐỔI THEO THỜI GIAN (vd suy thận cấp — AKI) —
    tổng quát hoá compute_cpred_two_compartment() cho trường hợp CL không hằng định suốt
    lịch sử liều. Khi cl_segments chỉ có 1 phần tử (CL không đổi), hàm này cho kết quả
    KHỚP TUYỆT ĐỐI compute_cpred_two_compartment() (đã kiểm định, sai số ~1e-14).

    cl_segments: list (thời_điểm_bắt_đầu_hiệu_lực, CL) đã sắp xếp tăng dần theo thời gian —
    CL có hiệu lực từ thời điểm đó cho tới thời điểm bắt đầu của đoạn kế tiếp (hoặc tới
    t_obs nếu là đoạn cuối). Thường mỗi đoạn ứng với 1 lần đo SCr — xem
    build_cl_segments_vanco(). Vc/Vp/Q giữ cố định xuyên suốt (không đổi theo AKI)."""
    if not cl_segments or not doses:
        return 0.0
    cl_segments = sorted(cl_segments, key=lambda s: s[0])
    doses_sorted = sorted(doses, key=lambda d: d.given_at)

    def cl_at(t: datetime.datetime) -> float:
        cl = cl_segments[0][1]
        for t_start, c in cl_segments:
            if t_start <= t:
                cl = c
        return cl

    t_start_all = min(cl_segments[0][0], doses_sorted[0].given_at)
    if t_obs <= t_start_all:
        return 0.0

    # Các mốc thời gian cần "cắt đoạn": đầu/cuối mỗi lần truyền dịch + mỗi lần đổi CL
    breakpoints = {t_start_all, t_obs}
    for d in doses_sorted:
        if t_start_all <= d.given_at <= t_obs:
            breakpoints.add(d.given_at)
            breakpoints.add(d.given_at + datetime.timedelta(hours=t_inf_h))
        elif d.given_at < t_start_all:
            breakpoints.add(t_start_all)
    for t_start, _ in cl_segments:
        if t_start_all <= t_start <= t_obs:
            breakpoints.add(t_start)
    bps = sorted(t for t in breakpoints if t_start_all <= t <= t_obs)

    a1, a2 = 0.0, 0.0
    for i in range(len(bps) - 1):
        seg_start, seg_end = bps[i], bps[i + 1]
        dt_h = (seg_end - seg_start).total_seconds() / 3600.0
        if dt_h <= 1e-12:
            continue
        cl_seg = cl_at(seg_start)
        rate = 0.0
        for d in doses_sorted:
            if d.given_at <= seg_start < d.given_at + datetime.timedelta(hours=t_inf_h):
                rate += d.dose_mg / t_inf_h
        a1, a2 = _segment_transition_2c(a1, a2, cl_seg, vc, vp, q, rate, dt_h)
    return a1 / vc


def build_cl_segments_vanco(scr_entries, recompute_priors_fn) -> List[Tuple[datetime.datetime, float]]:
    """Dựng danh sách đoạn (thời_điểm, CL) từ các lần đo SCr đã nhập — mỗi lần đo SCr mới
    mở ra 1 đoạn CL mới, có hiệu lực từ đúng thời điểm đo đó. scr_entries: list (giá_trị_
    mg/dL, thời_điểm_đo). recompute_priors_fn(scr_value) -> VancoPriors (đã có sẵn, dùng
    lại recompute_full_priors_goti/collin) — chỉ lấy .cl_prior để làm CL của đoạn."""
    if not scr_entries:
        return []
    entries_sorted = sorted(scr_entries, key=lambda e: e[1])
    return [(dt, recompute_priors_fn(scr).cl_prior) for scr, dt in entries_sorted]
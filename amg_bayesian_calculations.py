"""
amg_bayesian_calculations.py - Phuong phap Bayesian (mo hinh quan the Arechiga-Alvarado 2020,
1 ngan, IV truyen) cho TDM Aminoglycosid.

File nay HOAN TOAN TACH RIENG khoi pk_calculations.py (phuong phap Sawchuk-Zaske hien co) --
khong sua, khong dung chung dataclass/ham nao voi file do, de dam bao phuong phap cu giu
nguyen 100% nhu yeu cau. Cau truc va quy uoc dat ten phong theo vanco_calculations.py
(Goti/Collin) de nhat quan trong toan bo du an, nhung day la quan the hoc rieng (1 ngan,
2 tham so CL/Vd, khong co Q/Vp).

Da kiem chung bang file Excel "bayesian_aminoglycosid.xlsx" (sheet "Arechiga-Alvarado (2020)"):
IBW, CrCl (Cockcroft-Gault dung CAN NANG THUC - TBW, khong dung can nang hieu chinh), CLprior,
Vprior, Cpred (chong chat lieu 1 ngan), OFV tung diem va OFV tong deu khop <0.001% sai so.

LUU Y: cong thuc V/X (Cpred3, Cpred4) trong file Excel goc co loi copy-paste (tham chieu
nham cot T thay vi U o mot so dong) -- cac ham duoi day tai hien DUNG nguyen ly chong chat
lieu (moi Cpred_i dung dung cot thoi gian rieng cua no), khop voi dong 2 (dong duy nhat
khong bi loi) va khop voi logic tong quat ma nguoi dung mo ta.
"""

import datetime
import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple
from scipy.optimize import minimize


# ==========================================
# 1. DATACLASS
# ==========================================

@dataclass
class AmgPatientInfo:
    age: float
    gender: str            # 'nam' hoac 'nu'
    height_cm: float
    weight_kg: float        # TBW - dung truc tiep cho Cockcroft-Gault (khong hieu chinh)
    scr_value: float         # SCr do nguoi dung nhap (tu quy doi don vi)


@dataclass
class AmgDose:
    dose_mg: float
    given_at: datetime.datetime


@dataclass
class AmgMeasurement:
    c_obs: float
    t_obs: datetime.datetime
    t_inf_h: float = 1.0


@dataclass
class AmgPriors:
    cl_prior: float
    vd_prior: float
    omega_cl: float = 0.272
    omega_vd: float = 0.336


@dataclass
class AmgBayesResult:
    CL_optimized: float
    Vd_optimized: float
    Ke: float
    C_pred_final: float
    OFV_final: float
    success: bool
    message: str = ""
    points: list = field(default_factory=list)  # [{"t_obs","c_obs","c_pred","ofv"}]
    anchor_dose: object = None  # AmgDose "dang dung" (lieu ke truoc cac diem do cua block nay)


# Sai so du CO DINH cua mo hinh Arechiga-Alvarado 2020 (chi co SD cong gop, KHONG co CV%)
AA2020_SIGMA = 1.78


# ==========================================
# 2. TIEN NGHIEM QUAN THE (Arechiga-Alvarado 2020)
# ==========================================

def compute_scr_mgdl_amg(scr_value: float) -> float:
    """Tu quy doi don vi SCr: neu > 10 thi hieu la umol/L (chia 88.4), nguoc lai la mg/dL san."""
    return scr_value / 88.4 if scr_value > 10 else scr_value


def compute_ibw_amg(gender: str, height_cm: float) -> float:
    """IBW (Devine) -- dang quy doi theo cm, tai hien dung cong thuc C20 cua Excel."""
    over = max(0.0, height_cm - 152.4)
    return (50.0 + 0.9 * over) if gender.lower() in ("nam", "male", "m") else (45.5 + 0.9 * over)


def compute_crcl_amg(age: float, gender: str, weight_kg: float, scr_mgdl: float) -> float:
    """CrCl (Cockcroft-Gault) -- dung CAN NANG THUC (TBW), khong hieu chinh -- dung cong thuc C21."""
    if scr_mgdl <= 0 or age >= 140:
        return 0.0
    crcl = ((140.0 - age) * weight_kg) / (72.0 * scr_mgdl)
    return crcl if gender.lower() in ("nam", "male", "m") else crcl * 0.85


def compute_cl_prior_amg(crcl: float) -> float:
    """CLprior = 7.1 * (CrCl/130)^0.84 -- cong thuc C23."""
    return 7.1 * ((max(crcl, 1e-6) / 130.0) ** 0.84)


def compute_vd_prior_amg(ibw: float) -> float:
    """Vprior = 20.3 * (IBW/68)^2.94 -- cong thuc C24."""
    return 20.3 * ((max(ibw, 1e-6) / 68.0) ** 2.94)


def compute_population_priors_amg(patient: AmgPatientInfo) -> Tuple[AmgPriors, dict]:
    """Tinh CLprior/Vprior day du tu thong tin benh nhan (dung SCr dai dien -- thuong la lan
    do gan/moi nhat do UI cung cap).

    LUU Y VE DON VI: patient.scr_value PHAI DA o dang mg/dL (KHONG con tu doan don vi theo
    nguong >10 nua). Tu khi giao dien co o chon don vi tuong minh (mg/dL / umol/L) cho tung
    dong SCr, viec quy doi duoc UI thuc hien 1 LAN DUY NHAT truoc khi goi ham nay -- neu goi
    lai compute_scr_mgdl_amg() o day se GAY LOI CHIA 88.4 LAN 2 doi voi benh nhan suy than
    nang/loc mau co SCr thuc te > 10 mg/dL (khong hiem trong quan the dung aminoglycosid),
    lam SCr bi tinh sai thanh qua thap -> CLprior bi uoc luong sai qua cao. Neu can auto-doan
    don vi tu 1 gia tri tho chua ro don vi, hay tu goi compute_scr_mgdl_amg() truoc khi tao
    AmgPatientInfo, KHONG dua vao ham nay tu lam viec do."""
    ibw = compute_ibw_amg(patient.gender, patient.height_cm)
    scr_mgdl = patient.scr_value
    crcl = compute_crcl_amg(patient.age, patient.gender, patient.weight_kg, scr_mgdl)
    cl_prior = compute_cl_prior_amg(crcl)
    vd_prior = compute_vd_prior_amg(ibw)
    priors = AmgPriors(cl_prior=cl_prior, vd_prior=vd_prior)
    details = {"ibw": ibw, "scr_mgdl": scr_mgdl, "crcl": crcl}
    return priors, details


def recompute_cl_prior_amg(patient: AmgPatientInfo, scr_value: float) -> float:
    """Tinh lai CLprior voi 1 gia tri SCr KHAC (cua lan do gan Tobs cua 1 khoang dua lieu cu
    the) -- tuoi/gioi/can nang giu nguyen theo thong tin benh nhan. Dung cho cap nhat tuan tu
    qua nhieu lan TDM (yeu cau #4).

    LUU Y VE DON VI: scr_value PHAI DA o dang mg/dL -- xem giai thich chi tiet trong docstring
    cua compute_population_priors_amg() o tren (khong tu doan don vi theo nguong >10 nua)."""
    scr_mgdl = scr_value
    crcl = compute_crcl_amg(patient.age, patient.gender, patient.weight_kg, scr_mgdl)
    return compute_cl_prior_amg(crcl)


def find_nearest_scr_amg(scr_entries, t_obs):
    """scr_entries: list (scr_value, thoi_diem_do). Tra ve SCr co thoi diem do GAN t_obs NHAT."""
    if not scr_entries:
        return None
    return min(scr_entries, key=lambda e: abs((e[1] - t_obs).total_seconds()))[0]


# ==========================================
# 3. Cpred (CHONG CHAT LIEU, 1 NGAN) + OFV
# ==========================================

def compute_cpred_amg(cl: float, vd: float, doses: List[AmgDose],
                       t_obs: datetime.datetime, t_inf_h: float) -> float:
    """Nong do du doan tai t_obs = tong dong gop cua TAT CA cac lieu da truyen truoc do
    (nguyen ly chong chat lieu, mo hinh 1 ngan) -- tai hien dung cot R/T/V/X cua Excel:
        C_dose = (dose/(Tinf*CL)) * (1 - exp(-Ke*Tinf)) * exp(-Ke*p)   voi p = thoi gian
        SAU KHI DUNG TRUYEN den t_obs (p<0 -> lieu do chua dong gop, bo qua)."""
    ke = cl / vd if vd > 0 else 0.0
    if ke <= 0 or t_inf_h <= 0 or cl <= 0:
        return 0.0
    total = 0.0
    for d in doses:
        p = (t_obs - d.given_at).total_seconds() / 3600.0 - t_inf_h
        if p < 0:
            continue
        total += (d.dose_mg / (t_inf_h * cl)) * (1 - np.exp(-ke * t_inf_h)) * np.exp(-ke * p)
    return total


def _cl_segments_for_solve_amg(cl: float, doses: List[AmgDose], historical_cl_segments,
                                current_segment_start) -> List[Tuple[datetime.datetime, float]]:
    """Ghep cac doan CL da CO DINH tu nhung lan TDM truoc (historical_cl_segments) voi doan HIEN TAI
    dung "cl" (gia tri dang duoc toi uu), bat dau tu current_segment_start (mac dinh: lieu dau tien).
    Neu khong co lich su -> chi 1 doan duy nhat, tuong duong CL khong doi (hanh vi goc)."""
    seg_start = current_segment_start if current_segment_start is not None else min(d.given_at for d in doses)
    return list(historical_cl_segments or []) + [(seg_start, cl)]


def compute_ofv_amg(cl: float, vd: float, priors: AmgPriors, doses: List[AmgDose],
                     measurements: List[AmgMeasurement], sigma: float = AA2020_SIGMA,
                     historical_cl_segments=None, current_segment_start=None) -> float:
    """OFV_tong = OFV_CL + OFV_Vd + Sigma_i (Cobs_i - Cpred_i)^2 / sigma^2 (yeu cau #3, #4).
    Cpred dung CL BAC THANG THEO THOI GIAN (xu ly AKI) -- xem _cl_segments_for_solve_amg()."""
    ofv_cl = ((np.log(cl) - np.log(priors.cl_prior)) ** 2) / (priors.omega_cl ** 2)
    ofv_vd = ((np.log(vd) - np.log(priors.vd_prior)) ** 2) / (priors.omega_vd ** 2)
    segs = _cl_segments_for_solve_amg(cl, doses, historical_cl_segments, current_segment_start)
    ofv_points = 0.0
    for m in measurements:
        c_pred = compute_cpred_amg_piecewise(segs, vd, doses, m.t_obs, m.t_inf_h)
        ofv_points += ((m.c_obs - c_pred) ** 2) / (sigma ** 2)
    return ofv_cl + ofv_vd + ofv_points

# ==========================================
# 4. TOI UU HOA BAYES (1 khoang dua lieu / 1 lan goi)
# ==========================================

def solve_bayesian_posterior_amg(priors: AmgPriors, doses: List[AmgDose], measurements,
                                  sigma: float = AA2020_SIGMA,
                                  cl_min: float = 0.05, vd_min: float = 1.0,
                                  historical_cl_segments=None, current_segment_start=None) -> AmgBayesResult:
    """Toi uu (CL_post, Vd_post) de OFV nho nhat -- tuong duong GRG Nonlinear cua Excel Solver.
    Ho tro NHIEU diem do cung luc (measurements la list) -- khi do toi uu chung 1 lan (yeu cau #1)."""
    measurements = [measurements] if isinstance(measurements, AmgMeasurement) else list(measurements)
    if not doses:
        return AmgBayesResult(0, 0, 0, 0, 0, False, "Chua co du lieu lich su lieu dung.")
    if not measurements:
        return AmgBayesResult(0, 0, 0, 0, 0, False, "Chua co diem do Cobs/Tobs nao.")

    x0 = np.array([priors.cl_prior, priors.vd_prior], dtype=float)
    bounds = [(cl_min, None), (vd_min, None)]

    def objective(x):
        return compute_ofv_amg(x[0], x[1], priors, doses, measurements, sigma,
                                historical_cl_segments, current_segment_start)

    best = None
    for method in ("L-BFGS-B", "SLSQP"):
        try:
            res = minimize(objective, x0, method=method, bounds=bounds,
                            options={"maxiter": 500, "ftol": 1e-12})
            if res.success and (best is None or res.fun < best.fun):
                best = res
        except Exception:
            continue
    if best is None:
        return AmgBayesResult(0, 0, 0, 0, 0, False, "Thuat toan toi uu khong hoi tu.")

    cl_opt, vd_opt = best.x
    ke = cl_opt / vd_opt
    measurements_sorted = sorted(measurements, key=lambda m: m.t_obs)
    cl_segments_final = _cl_segments_for_solve_amg(cl_opt, doses, historical_cl_segments, current_segment_start)
    points = []
    for m in measurements_sorted:
        c_pred_i = compute_cpred_amg_piecewise(cl_segments_final, vd_opt, doses, m.t_obs, m.t_inf_h)
        ofv_i = ((m.c_obs - c_pred_i) ** 2) / (sigma ** 2)
        points.append({"t_obs": m.t_obs, "c_obs": m.c_obs, "c_pred": float(c_pred_i), "ofv": float(ofv_i)})
    c_pred_final = points[-1]["c_pred"] if points else 0.0

    return AmgBayesResult(CL_optimized=float(cl_opt), Vd_optimized=float(vd_opt), Ke=float(ke),
                           C_pred_final=float(c_pred_final), OFV_final=float(best.fun),
                           success=True, message="Da hoi tu thanh cong.", points=points)


# ==========================================
# 5. NHIEU LAN TDM (Sequential Bayesian theo occasion, giong kien truc vanco_calculations.py)
# ==========================================

def group_measurements_by_dose_block_amg(measurements: List[AmgMeasurement], doses: List[AmgDose]):
    """Gom diem do theo 'khoang dua lieu' dang hieu luc tai Tobs: lieu neo (anchor) = lieu co
    given_at MUON NHAT nhung <= Tobs. Cung lieu neo -> cung block, chay OFV chung 1 lan."""
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


def recompute_full_priors_amg(patient: AmgPatientInfo, scr_value: float) -> AmgPriors:
    """Tinh lai TOAN BO tien nghiem (CL/Vd) theo mo hinh Arechiga-Alvarado 2020 tu 1 gia tri
    SCr cu the (mg/dL, cua lan do gan Tobs cua 1 khoang dua lieu cu the) -- dung cho MOI lan
    TDM (ke ca lan dau), KHONG ke thua hau nghiem cua lan TDM truoc. Ly do (giong het
    vanco_calculations.recompute_full_priors_goti()): omega_vd do do bien thien GIUA CAC
    BENH NHAN so voi quan the, khong phai do tin cay cua 1 uoc luong hau nghiem tu du lieu
    thua (thuong chi 1 mau) cua lan truoc -- neu ke thua hau nghiem lam tien nghiem moi ma
    van dung omega quan the goc, sai lech ngau nhien cua 1 lan do se neo lai vinh vien qua
    cac lan sau (hien tuong "troi dat" ra khoi quan the tham khao)."""
    patient_i = AmgPatientInfo(age=patient.age, gender=patient.gender, height_cm=patient.height_cm,
                                weight_kg=patient.weight_kg, scr_value=scr_value)
    priors, _ = compute_population_priors_amg(patient_i)
    return priors


def solve_bayesian_sequential_amg(doses: List[AmgDose], blocks: list, recompute_priors_fn,
                                   nearest_scr_fn, sigma: float = AA2020_SIGMA):
    """Toi uu Bayes qua tung block (moi block = 1 khoang dua lieu).

    (1) Tien nghiem: MOI block (ke ca block dau) dung tien nghiem CL/Vd TINH LAI HOAN TOAN MOI tu mo
    hinh quan the (recompute_priors_fn), dung SCr gan Tobs cua CHINH block do -- khong ke thua Vd hau
    nghiem cua block truoc (tranh troi dat khoi quan the goc).

    (2) Cpred voi CL BAC THANG (xu ly AKI): CL_post cua lan TDM k la CL cua KHOANG THOI GIAN TU lan TDM
    k-1 DEN lan TDM k (lan 1: tu lieu dau tien den TDM 1). Khi giai block k, cac doan truoc dung CL_post
    CO DINH da uoc luong; chi doan (TDM k-1, TDM k] dung CL dang toi uu. Ranh gioi doan = thoi diem do
    cua lan TDM truoc (KHONG phai thoi diem lay SCr -- SCr thuong lay cung luc mau dinh/day, neu lay
    lam ranh gioi thi doan hien tai co do dai 0 va Cobs khong con tham gia uoc luong CL).

    nearest_scr_fn(t_obs) -> scr_value (mg/dL), chi dung de tinh CL_prior.
    Tra ve list AmgBayesResult -- phan tu CUOI la ket qua can hien thi/luu (yeu cau #4)."""
    results = []
    seg_start = min(d.given_at for d in doses)
    historical_segments: List[Tuple[datetime.datetime, float]] = []
    for block in blocks:
        scr_i = nearest_scr_fn(block["measurements"][0].t_obs)
        priors_i = recompute_priors_fn(scr_i)
        res = solve_bayesian_posterior_amg(priors_i, doses, block["measurements"], sigma=sigma,
                                            historical_cl_segments=historical_segments,
                                            current_segment_start=seg_start)
        res.anchor_dose = block["anchor_dose"]
        results.append(res)
        if not res.success:
            break
        historical_segments = historical_segments + [(seg_start, res.CL_optimized)]
        seg_start = max(m.t_obs for m in block["measurements"])
    return results

# ==========================================
# 6. Cpeak/Ctrough HIEN TAI (trang thai on dinh cua lieu+tau dang dung) + mo phong duong cong
# ==========================================

def compute_css_peak_trough_amg(dose_mg: float, tau_h: float, tinf_h: float, cl: float, vd: float):
    """Cpeak/Ctrough O TRANG THAI ON DINH (steady state) voi lieu+tau DANG DUNG -- cong thuc
    F15/F16 (hoac F18/F19 khi chinh lieu) cua Excel."""
    ke = cl / vd if vd > 0 else 0.0
    if ke <= 0 or tau_h <= 0 or tinf_h <= 0 or cl <= 0:
        return 0.0, 0.0
    cpeak = ((dose_mg / (tinf_h * cl)) * (1 - np.exp(-ke * tinf_h))) / (1 - np.exp(-ke * tau_h))
    ctrough = cpeak * np.exp(-ke * (tau_h - tinf_h))
    return float(cpeak), float(ctrough)


def simulate_concentration_curve_amg(cl: float, vd: float, doses: List[AmgDose], t_inf_h: float,
                                      t_end: datetime.datetime, n_points: int = 300):
    """Mo phong duong cong nong do theo thoi gian -- dung cho bieu do (Muc 7, giong Vancomycin)."""
    if not doses:
        return [], []
    t_start = min(d.given_at for d in doses)
    total_h = (t_end - t_start).total_seconds() / 3600.0
    if total_h <= 0:
        return [], []
    times_h = np.linspace(0, total_h, n_points)
    times_abs = [t_start + datetime.timedelta(hours=float(h)) for h in times_h]
    concs = [compute_cpred_amg(cl, vd, doses, t, t_inf_h) for t in times_abs]
    return times_abs, concs


# ==========================================
# 7. Cpred VOI CL BAC THANG THEO THOI GIAN (xu ly AKI / suy than cap trong lich su lieu)
#    Da kiem dinh: khop compute_cpred_amg() khi CL khong doi (sai so 0) va khop loi giai ODE
#    (scipy solve_ivp) toi ~1e-9 khi CL doi bac thang.
# ==========================================

def _segment_transition_1c(a0: float, cl: float, vd: float, rate_mg_per_h: float, dt_h: float) -> float:
    """Chuyen luong thuoc A (1 ngan) qua dt_h voi CL/Vd co dinh va toc do truyen rate khong doi:
    nghiem dong cua dA/dt = rate - k*A :  A(t+dt) = A0*e^(-k*dt) + (rate/k)*(1 - e^(-k*dt))."""
    k = cl / vd if vd > 0 else 0.0
    if k <= 0:
        return a0 + rate_mg_per_h * dt_h
    decay = np.exp(-k * dt_h)
    if rate_mg_per_h:
        return a0 * decay + (rate_mg_per_h / k) * (1 - decay)
    return a0 * decay


def compute_cpred_amg_piecewise(cl_segments: List[Tuple[datetime.datetime, float]], vd: float,
                                 doses: List[AmgDose], t_obs: datetime.datetime,
                                 t_inf_h: float) -> float:
    """Nong do du doan tai t_obs khi CL THAY DOI THEO THOI GIAN (vd AKI): tong quat hoa
    compute_cpred_amg(). cl_segments: list (thoi_diem_bat_dau_hieu_luc, CL) -- CL co hieu luc tu thoi
    diem do cho toi doan ke tiep (hoac toi t_obs). Vd giu co dinh. Moc truoc doan dau tien dung CL cua
    doan dau tien. Voi 1 doan duy nhat cho ket qua trung compute_cpred_amg()."""
    if not cl_segments or not doses:
        return 0.0
    cl_segments = sorted(cl_segments, key=lambda s: s[0])
    doses_sorted = sorted(doses, key=lambda d: d.given_at)

    def cl_at(t: datetime.datetime) -> float:
        cl = cl_segments[0][1]
        for t_start, c_ in cl_segments:
            if t_start <= t:
                cl = c_
        return cl

    t_start_all = min(cl_segments[0][0], doses_sorted[0].given_at)
    if t_obs <= t_start_all:
        return 0.0
    breakpoints = {t_start_all, t_obs}
    for d in doses_sorted:
        if t_start_all <= d.given_at <= t_obs:
            breakpoints.add(d.given_at)
            breakpoints.add(d.given_at + datetime.timedelta(hours=t_inf_h))
    for t_start, _ in cl_segments:
        if t_start_all <= t_start <= t_obs:
            breakpoints.add(t_start)
    bps = sorted(t for t in breakpoints if t_start_all <= t <= t_obs)

    a = 0.0
    for i in range(len(bps) - 1):
        seg_start, seg_end = bps[i], bps[i + 1]
        dt_h = (seg_end - seg_start).total_seconds() / 3600.0
        if dt_h <= 1e-12:
            continue
        rate = 0.0
        for d in doses_sorted:
            if d.given_at <= seg_start < d.given_at + datetime.timedelta(hours=t_inf_h):
                rate += d.dose_mg / t_inf_h
        a = _segment_transition_1c(a, cl_at(seg_start), vd, rate, dt_h)
    return a / vd


def build_cl_segments_from_results_amg(block_results, doses: List[AmgDose]) -> List[Tuple[datetime.datetime, float]]:
    """Dung danh sach doan CL (thoi_diem_bat_dau, CL) tu KET QUA cac lan TDM da giai: doan 1 bat dau tu
    lieu dau tien voi CL_post lan 1; doan k bat dau tai thoi diem do cua lan TDM k-1 voi CL_post lan k.
    Doan cuoi (CL_post moi nhat) keo dai ve sau -- dung cho do thi nhat quan voi cach tinh OFV."""
    if not doses:
        return []
    segs: List[Tuple[datetime.datetime, float]] = []
    seg_start = min(d.given_at for d in doses)
    for r in block_results:
        if not getattr(r, "points", None):
            continue
        segs.append((seg_start, r.CL_optimized))
        seg_start = max(p["t_obs"] for p in r.points)
    return segs


def simulate_concentration_curve_amg_piecewise(cl_segments, vd: float, doses: List[AmgDose], t_inf_h: float,
                                                t_end: datetime.datetime, n_points: int = 300):
    """Giong simulate_concentration_curve_amg() nhung CL thay doi theo tung doan -- duong cong di qua
    dung cac Cobs cua tung lan TDM."""
    if not doses or not cl_segments:
        return [], []
    t_start = min(d.given_at for d in doses)
    total_h = (t_end - t_start).total_seconds() / 3600.0
    if total_h <= 0:
        return [], []
    times_abs = [t_start + datetime.timedelta(hours=float(h)) for h in np.linspace(0, total_h, n_points)]
    concs = [compute_cpred_amg_piecewise(cl_segments, vd, doses, t, t_inf_h) for t in times_abs]
    return times_abs, concs

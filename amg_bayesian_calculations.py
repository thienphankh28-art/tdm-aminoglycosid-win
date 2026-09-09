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


def compute_ofv_amg(cl: float, vd: float, priors: AmgPriors, doses: List[AmgDose],
                     measurements: List[AmgMeasurement], sigma: float = AA2020_SIGMA) -> float:
    """OFV_tong = OFV_CL + OFV_Vd + Sigma_i (Cobs_i - Cpred_i)^2 / sigma^2 (yeu cau #3, #4)."""
    ofv_cl = ((np.log(cl) - np.log(priors.cl_prior)) ** 2) / (priors.omega_cl ** 2)
    ofv_vd = ((np.log(vd) - np.log(priors.vd_prior)) ** 2) / (priors.omega_vd ** 2)
    ofv_points = 0.0
    for m in measurements:
        c_pred = compute_cpred_amg(cl, vd, doses, m.t_obs, m.t_inf_h)
        ofv_points += ((m.c_obs - c_pred) ** 2) / (sigma ** 2)
    return ofv_cl + ofv_vd + ofv_points


# ==========================================
# 4. TOI UU HOA BAYES (1 khoang dua lieu / 1 lan goi)
# ==========================================

def solve_bayesian_posterior_amg(priors: AmgPriors, doses: List[AmgDose], measurements,
                                  sigma: float = AA2020_SIGMA,
                                  cl_min: float = 0.05, vd_min: float = 1.0) -> AmgBayesResult:
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
        return compute_ofv_amg(x[0], x[1], priors, doses, measurements, sigma)

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
    points = []
    for m in measurements_sorted:
        c_pred_i = compute_cpred_amg(cl_opt, vd_opt, doses, m.t_obs, m.t_inf_h)
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


def solve_bayesian_sequential_amg(doses: List[AmgDose], blocks: list, initial_priors: AmgPriors,
                                   recompute_cl_fn, nearest_scr_fn, sigma: float = AA2020_SIGMA):
    """Toi uu Bayes TUAN TU qua tung block (moi block = 1 khoang dua lieu):
      - Block 1: dung nguyen initial_priors (CL/Vd tu mo hinh quan the AA2020).
      - Block k>=2: Vd_prior = Vd_post(k-1); CL_prior = recompute_cl_fn(SCr gan Tobs dau
        tien cua block k) -- cap nhat lai theo chuc nang than moi nhat.
    Tra ve list AmgBayesResult -- phan tu CUOI la ket qua can hien thi/luu (yeu cau #4)."""
    results = []
    priors = initial_priors
    for i, block in enumerate(blocks):
        if i > 0:
            scr_i = nearest_scr_fn(block["measurements"][0].t_obs)
            cl_prior_i = recompute_cl_fn(scr_i) if scr_i is not None else priors.cl_prior
            priors = AmgPriors(cl_prior=cl_prior_i, vd_prior=priors.vd_prior,
                                omega_cl=initial_priors.omega_cl, omega_vd=initial_priors.omega_vd)
        res = solve_bayesian_posterior_amg(priors, doses, block["measurements"], sigma=sigma)
        res.anchor_dose = block["anchor_dose"]
        results.append(res)
        if res.success:
            priors = AmgPriors(cl_prior=res.CL_optimized, vd_prior=res.Vd_optimized,
                                omega_cl=initial_priors.omega_cl, omega_vd=initial_priors.omega_vd)
        else:
            break
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

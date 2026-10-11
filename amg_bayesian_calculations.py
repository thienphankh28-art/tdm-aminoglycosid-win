"""
amg_bayesian_calculations.py - Phuong phap Bayesian (mo hinh quan the Arechiga-Alvarado 2020,
1 ngan, IV truyen) cho TDM AMIKACIN.

File nay HOAN TOAN TACH RIENG khoi pk_calculations.py (phuong phap Sawchuk-Zaske) -- khong dung
chung dataclass/ham nao voi file do.

NGUON: Arechiga-Alvarado NA et al. Antimicrob Agents Chemother 2020;64(5):e02178-19.
  CL (L/h) = 7.1 x (CLCR/130)^0.84           (CLCR: Cockcroft-Gault, CAN NANG THUC TBW, mL/min)
  V  (L)   = 20.3 x (IBW/68)^2.94
  Bien thien giua nguoi DANG TI LE (Bang 2, chu thich):  CLi = CL x (1 + etaCL),  Vi = V x (1 + etaV)
      omega_CL = 27.2 %, omega_V = 33.6 %   (CV, tuc SD cua eta = 0.272 / 0.336)
  Sai so du CONG (homoscedastic): sigma = 1.78 mg/L (SD).

PHIEN BAN 11/10/2026 -- cac thay doi so voi ban 5/10 (theo bai bao va quyet dinh cua nguoi dung):
  1. Phat tien nghiem IIV theo DANG TI LE nhu bai bao: (eta/omega)^2 voi eta = CLi/CLpop - 1
     (truoc day dung dang log: ln(CL/CLprior)^2/omega^2).
  2. Thoi gian truyen (Tinf) gan voi TUNG LIEU (AmgDose.t_inf_h), khong con lay theo diem do.
  3. Khop CHUNG tat ca cac mau (1 eta_CL, 1 eta_V cho ca dot dieu tri) voi CrCl BIEN THIEN THEO THOI GIAN:
        CL(t) = 7.1 x (CrCl(t)/130)^0.84 x (1 + eta_CL)
     CrCl(t) tinh tu SCr(t) -- noi suy TUYEN TINH giua cac lan do SCr, giu hang so truoc lan do dau
     va sau lan do cuoi. Thay cho cach cu (moi lan TDM mot tien nghiem moi + CL bac thang rieng).
  4. Mau lay trong luc truyen van duoc tinh dung (mo hinh xu ly lien tuc) nhung co CANH BAO.
  5. Bo ham tu doan don vi SCr (compute_scr_mgdl_amg): don vi do nguoi dung chon, quy doi DUNG 1 LAN
     (scr_to_mgdl) truoc khi dua vao bat ky ham tinh toan nao. Moi ham trong file nay nhan SCr da la mg/dL.
  6. Them check_model_applicability_amg(): canh bao khi benh nhan/du lieu nam ngoai khoang cua bai bao.
"""

import datetime
import math
import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from scipy.optimize import minimize


# ==========================================
# 0. HANG SO CUA MO HINH (Bang 2 bai bao)
# ==========================================

AA2020_THETA_CL = 7.1
AA2020_EXP_CL = 0.84
AA2020_CRCL_REF = 130.0
AA2020_THETA_V = 20.3
AA2020_EXP_V = 2.94
AA2020_IBW_REF = 68.0
AA2020_OMEGA_CL = 0.272      # SD cua eta_CL (dang ti le)
AA2020_OMEGA_V = 0.336       # SD cua eta_V  (dang ti le)
AA2020_SIGMA = 1.78          # SD sai so du cong (mg/L)

# Khoang du lieu cua quan the xay dung/kiem dinh mo hinh (Bang 1 + phan Ket qua) -- dung de canh bao
AA2020_RANGES = {
    "age": (18.0, 67.0),              # 18-64 (xay dung), 18-67 (kiem dinh)
    "weight": (44.0, 138.0),          # kg
    "ibw": (52.0, 84.0),              # 68.1 +/- 2 SD (SD 8.1)
    "scr": (0.2, 1.8),                # mg/dL
    "crcl": (49.0, 211.0),            # 130 +/- 2 SD (SD 40.6) -- uoc luong, bai khong cong bo min-max
    "cobs": (2.0, 50.0),              # 2-48.7 (dinh luong), thang hieu chuan 2-50 mg/L
    "dose_day": (500.0, 1000.0),      # mg/ngay (trung vi 1000, khoang 500-1000)
    "post_infusion_min_h": 0.5,       # mau lay >= 30 phut sau khi ket thuc truyen
    "post_dose_max_h": 16.5,          # mau xa nhat 16.5 gio sau lieu
}


# ==========================================
# 1. DATACLASS
# ==========================================

@dataclass
class AmgPatientInfo:
    age: float
    gender: str            # 'nam' hoac 'nu'
    height_cm: float
    weight_kg: float        # TBW - dung truc tiep cho Cockcroft-Gault (khong hieu chinh)
    scr_value: float         # SCr DAI DIEN, DA O DANG mg/dL (khong tu quy doi don vi)


@dataclass
class AmgDose:
    dose_mg: float
    given_at: datetime.datetime      # thoi diem BAT DAU truyen
    t_inf_h: float = 1.0             # thoi gian truyen CUA LIEU NAY (h)


@dataclass
class AmgMeasurement:
    c_obs: float
    t_obs: datetime.datetime
    t_inf_h: float = 1.0             # (ton tai de tuong thich du lieu cu -- KHONG con duoc dung khi tinh)


@dataclass
class AmgPriors:
    cl_prior: float
    vd_prior: float
    omega_cl: float = AA2020_OMEGA_CL
    omega_vd: float = AA2020_OMEGA_V


@dataclass
class AmgBayesResult:
    CL_optimized: float            # CL HIEN TAI (tai thoi diem SCr moi nhat, da nhan (1+eta_CL))
    Vd_optimized: float
    Ke: float
    C_pred_final: float
    OFV_final: float
    success: bool
    message: str = ""
    points: list = field(default_factory=list)  # [{"t_obs","c_obs","c_pred","ofv","dose_index","in_infusion",...}]
    anchor_dose: object = None     # AmgDose lien truoc diem do cuoi cung (de lay liều/tau hien dang dung)
    eta_cl: float = 0.0
    eta_vd: float = 0.0
    cl_pop_current: float = 0.0    # CL quan the tai SCr moi nhat (chua nhan eta)
    vd_pop: float = 0.0
    crcl_current: float = 0.0
    ofv_prior: float = 0.0         # phan phat tien nghiem (eta/omega)^2
    ofv_obs: float = 0.0           # phan sai so quan sat
    n_used: int = 0                # so diem do duoc dung


# ==========================================
# 2. DON VI SCr (quy doi DUNG 1 LAN)
# ==========================================

def scr_to_mgdl(value: float, unit: str) -> float:
    """Quy doi SCr nguoi dung nhap sang mg/dL THEO DON VI HO CHON (khong doan don vi theo nguong).
    Chi duoc goi 1 LAN o tang giao dien; moi ham tinh toan ben duoi nhan SCr da la mg/dL."""
    u = str(unit).strip().lower().replace("µ", "u").replace("μ", "u")
    if u.startswith("umol") or u.startswith("micromol"):
        return float(value) / 88.4
    if u.startswith("mg"):
        return float(value)
    raise ValueError(f"Đơn vị SCr không hợp lệ: {unit!r}")


# ==========================================
# 3. TIEN NGHIEM QUAN THE (Arechiga-Alvarado 2020)
# ==========================================

def compute_ibw_amg(gender: str, height_cm: float) -> float:
    """IBW (Devine) -- bai bao KHONG neu cong thuc IBW; dung Devine theo thong le
    (luu y: Bang 1 cua bai cho IBW trung binh cao hon Devine khoang 2.6 kg -- chua xac minh)."""
    over = max(0.0, height_cm - 152.4)
    return (50.0 + 0.9 * over) if gender.lower() in ("nam", "male", "m") else (45.5 + 0.9 * over)


def compute_crcl_amg(age: float, gender: str, weight_kg: float, scr_mgdl: float) -> float:
    """CrCl (Cockcroft-Gault) dung CAN NANG THUC (TBW) -- dung theo bai bao. SCr: mg/dL."""
    if scr_mgdl <= 0 or age >= 140:
        return 0.0
    crcl = ((140.0 - age) * weight_kg) / (72.0 * scr_mgdl)
    return crcl if gender.lower() in ("nam", "male", "m") else crcl * 0.85


def compute_cl_prior_amg(crcl: float) -> float:
    """CL quan the = 7.1 * (CrCl/130)^0.84 (L/h)."""
    return AA2020_THETA_CL * ((max(crcl, 1e-6) / AA2020_CRCL_REF) ** AA2020_EXP_CL)


def compute_vd_prior_amg(ibw: float) -> float:
    """V quan the = 20.3 * (IBW/68)^2.94 (L)."""
    return AA2020_THETA_V * ((max(ibw, 1e-6) / AA2020_IBW_REF) ** AA2020_EXP_V)


def compute_population_priors_amg(patient: AmgPatientInfo) -> Tuple[AmgPriors, dict]:
    """CLpop/Vpop tai SCr dai dien trong patient.scr_value (PHAI da la mg/dL)."""
    ibw = compute_ibw_amg(patient.gender, patient.height_cm)
    scr_mgdl = patient.scr_value
    crcl = compute_crcl_amg(patient.age, patient.gender, patient.weight_kg, scr_mgdl)
    priors = AmgPriors(cl_prior=compute_cl_prior_amg(crcl), vd_prior=compute_vd_prior_amg(ibw))
    return priors, {"ibw": ibw, "scr_mgdl": scr_mgdl, "crcl": crcl}


# ==========================================
# 4. SCr(t) -> CrCl(t) -> CL quan the theo thoi gian
# ==========================================

def _sorted_scr(scr_entries):
    es = sorted([(float(s), t) for s, t in scr_entries if s is not None and float(s) > 0], key=lambda e: e[1])
    if not es:
        raise ValueError("Cần ít nhất 1 lần đo SCr hợp lệ (> 0).")
    return es


def find_nearest_scr_amg(scr_entries, t_obs):
    """(giu lai de tuong thich) SCr co thoi diem do gan t_obs nhat."""
    if not scr_entries:
        return None
    return min(scr_entries, key=lambda e: abs((e[1] - t_obs).total_seconds()))[0]


# ==========================================
# 5. GAN MAU VAO LIEU + MO PHONG THEO THOI GIAN
# ==========================================

def assign_measurements_amg(measurements: List[AmgMeasurement], doses: List[AmgDose]) -> list:
    """Voi moi diem do, xac dinh LIEU lien truoc (lieu co given_at muon nhat nhung <= t_obs, danh so theo
    thu tu thoi gian, bat dau tu 0). Tra ve list dict (dung thu tu measurements dau vao):
      dose_index (None neu mau truoc lieu dau), hours_after_start, hours_after_end (am = dang truyen),
      in_infusion (True neu mau nam TRONG thoi gian truyen cua lieu do)."""
    ds = sorted(doses, key=lambda d: d.given_at)
    out = []
    for m in measurements:
        idx = None
        for i, d in enumerate(ds):
            if d.given_at <= m.t_obs:
                idx = i
            else:
                break
        if idx is None:
            out.append({"measurement": m, "dose_index": None, "dose": None, "hours_after_start": None,
                        "hours_after_end": None, "in_infusion": False})
            continue
        d = ds[idx]
        hs = (m.t_obs - d.given_at).total_seconds() / 3600.0
        out.append({"measurement": m, "dose_index": idx, "dose": d, "hours_after_start": hs,
                    "hours_after_end": hs - d.t_inf_h, "in_infusion": hs < d.t_inf_h})
    return out


class AmgTimeline:
    """Luoi thoi gian de tich phan  dA/dt = R(t) - k(t)*A,  k(t) = CL(t)/V,  CL(t) = CLpop(CrCl(t)) * (1+eta_CL).
    Cac moc: moi bat dau/ket thuc truyen, moi lan do SCr, moi thoi diem can du doan. Doan nao nam trong vung
    SCr bien thien duoc chia nho toi da dt_max gio (k tinh o diem giua doan; nghiem dong trong tung doan).
    Luoi chi phu thuoc benh nhan/SCr/lieu -- KHONG phu thuoc eta, V -- nen dung lai nhieu lan khi toi uu."""

    def __init__(self, patient: AmgPatientInfo, scr_entries, doses: List[AmgDose], eval_times, dt_max: float = 0.25):
        if not doses:
            raise ValueError("Chưa có liều.")
        ds = sorted(doses, key=lambda d: d.given_at)
        self.doses = ds
        self.t_start = ds[0].given_at
        H = lambda t: (t - self.t_start).total_seconds() / 3600.0
        scr = _sorted_scr(scr_entries)
        scr_h = np.array([H(t) for _, t in scr])
        scr_v = np.array([s for s, _ in scr])
        self._scr_h, self._scr_v = scr_h, scr_v
        self.scr_last = float(scr_v[-1])
        self.patient = patient
        eval_h = [H(t) for t in eval_times]
        self.eval_h = eval_h
        pos = [h for h in eval_h if h > 0]
        self.t_max_h = max(pos) if pos else 0.0

        bps = {0.0, self.t_max_h}
        for d in ds:
            bps.add(H(d.given_at))
            bps.add(H(d.given_at) + float(d.t_inf_h))
        bps.update(h for h in scr_h if 0 < h < self.t_max_h)
        bps.update(pos)
        bps = sorted(b for b in bps if 0.0 <= b <= self.t_max_h)
        var_lo, var_hi = float(scr_h[0]), float(scr_h[-1])   # vung SCr bien thien

        starts, dts, rates, cl_pops, crcls = [], [], [], [], []
        for a, b in zip(bps[:-1], bps[1:]):
            if b - a <= 1e-12:
                continue
            n = 1
            if len(scr_h) > 1 and b > var_lo and a < var_hi:
                n = max(1, int(math.ceil((b - a) / dt_max)))
            step = (b - a) / n
            for j in range(n):
                s0 = a + j * step
                mid = s0 + step / 2.0
                rate = 0.0
                for d in ds:
                    d0 = H(d.given_at)
                    if d0 <= mid < d0 + float(d.t_inf_h):
                        rate += d.dose_mg / float(d.t_inf_h)
                scr_mid = float(np.interp(mid, scr_h, scr_v))
                crcl = compute_crcl_amg(patient.age, patient.gender, patient.weight_kg, scr_mid)
                starts.append(s0)
                dts.append(step)
                rates.append(rate)
                crcls.append(crcl)
                cl_pops.append(compute_cl_prior_amg(crcl))
        self.starts = np.array(starts)
        self.dts = np.array(dts)
        self.rates = np.array(rates)
        self.cl_pop = np.array(cl_pops)
        self.crcl = np.array(crcls)
        self.ends = self.starts + self.dts
        # chi so doan ket thuc tai moi thoi diem du doan
        self.eval_idx = []
        for h in eval_h:
            if h <= 0 or len(self.ends) == 0:
                self.eval_idx.append(-1)
            else:
                self.eval_idx.append(int(np.argmin(np.abs(self.ends - h))))
        # CL quan the "hien tai" = tai SCr moi nhat (hoac sau do)
        crcl_now = compute_crcl_amg(patient.age, patient.gender, patient.weight_kg, self.scr_last)
        self.crcl_now = crcl_now
        self.cl_pop_now = compute_cl_prior_amg(crcl_now)

    def concentrations(self, eta_cl: float, eta_v: float, vd_pop: float) -> List[float]:
        """Nong do tai cac thoi diem du doan (theo thu tu eval_times), voi CL(t)=CLpop(t)(1+eta_cl), V=vd_pop(1+eta_v)."""
        V = vd_pop * (1.0 + eta_v)
        f = 1.0 + eta_cl
        if V <= 0 or f <= 0 or len(self.dts) == 0:
            return [0.0] * len(self.eval_h)
        k = f * self.cl_pop / V
        decay = np.exp(-k * self.dts)
        gain = (self.rates / k) * (1.0 - decay)
        amount = np.empty(len(k))
        a = 0.0
        for i in range(len(k)):
            a = a * decay[i] + gain[i]
            amount[i] = a
        return [0.0 if idx < 0 else float(amount[idx] / V) for idx in self.eval_idx]


def simulate_concentration_curve_amg_tv(patient: AmgPatientInfo, scr_entries, doses: List[AmgDose],
                                         eta_cl: float, vd: float, t_end: datetime.datetime, n_points: int = 300):
    """Duong cong C(t) dung CL(t) bien thien theo SCr. vd = V cuoi cung (da nhan (1+eta_V))."""
    if not doses:
        return [], []
    t_start = min(d.given_at for d in doses)
    total_h = (t_end - t_start).total_seconds() / 3600.0
    if total_h <= 0:
        return [], []
    times = [t_start + datetime.timedelta(hours=float(h)) for h in np.linspace(0, total_h, n_points)]
    tl = AmgTimeline(patient, scr_entries, doses, times)
    return times, tl.concentrations(eta_cl, 0.0, vd)


def compute_cpred_amg(cl: float, vd: float, doses: List[AmgDose], t_obs: datetime.datetime,
                       t_inf_h: Optional[float] = None) -> float:
    """Nong do du doan voi CL HANG SO (cong thuc dong, chong chat lieu) -- dung de doi chieu/kiem tra.
    Mau lay TRONG luc truyen duoc tinh dung (pha tang). t_inf_h=None -> dung Tinf cua tung lieu."""
    ke = cl / vd if vd > 0 else 0.0
    if ke <= 0 or cl <= 0:
        return 0.0
    total = 0.0
    for d in doses:
        ti = float(d.t_inf_h if t_inf_h is None else t_inf_h)
        el = (t_obs - d.given_at).total_seconds() / 3600.0
        if el <= 0 or ti <= 0:
            continue
        base = d.dose_mg / (ti * cl)
        total += base * (1 - math.exp(-ke * el)) if el <= ti else base * (1 - math.exp(-ke * ti)) * math.exp(-ke * (el - ti))
    return total


# ==========================================
# 6. TOI UU HOA BAYES (MAP) -- KHOP CHUNG TAT CA CAC MAU
# ==========================================

def solve_bayesian_joint_amg(patient: AmgPatientInfo, scr_entries, doses: List[AmgDose],
                              measurements: List[AmgMeasurement], sigma: float = AA2020_SIGMA,
                              omega_cl: float = AA2020_OMEGA_CL, omega_v: float = AA2020_OMEGA_V,
                              cl_min: float = 0.05, vd_min: float = 1.0) -> AmgBayesResult:
    """Uoc luong (eta_CL, eta_V) cho CA DOT DIEU TRI bang cuc tieu hoa
        OFV = (eta_CL/omega_CL)^2 + (eta_V/omega_V)^2 + SUM_i ((Cobs_i - Cpred_i)/sigma)^2
    (IIV dang ti le theo bai bao). Cpred_i tinh bang tich phan voi CL(t) = CLpop(CrCl(t))*(1+eta_CL) va Tinf cua
    tung lieu. Diem do TRUOC lieu dau tien bi bo qua."""
    if not doses:
        return AmgBayesResult(0, 0, 0, 0, 0, False, "Chưa có dữ liệu lịch sử liều dùng.")
    if not measurements:
        return AmgBayesResult(0, 0, 0, 0, 0, False, "Chưa có điểm đo Cobs/Tobs nào.")
    try:
        _sorted_scr(scr_entries)
    except ValueError as e:
        return AmgBayesResult(0, 0, 0, 0, 0, False, str(e))
    ds = sorted(doses, key=lambda d: d.given_at)
    if any(d.t_inf_h <= 0 or d.dose_mg <= 0 for d in ds):
        return AmgBayesResult(0, 0, 0, 0, 0, False, "Mỗi liều phải có liều (mg) > 0 và thời gian truyền > 0.")
    used = sorted([m for m in measurements if m.t_obs > ds[0].given_at], key=lambda m: m.t_obs)
    if not used:
        return AmgBayesResult(0, 0, 0, 0, 0, False, "Mọi điểm đo (Tobs) đều nằm trước liều đầu tiên.")

    vd_pop = compute_vd_prior_amg(compute_ibw_amg(patient.gender, patient.height_cm))
    tl = AmgTimeline(patient, scr_entries, ds, [m.t_obs for m in used])
    cobs = np.array([m.c_obs for m in used], dtype=float)

    lb_cl = max(-0.95, cl_min / max(tl.cl_pop_now, 1e-9) - 1.0)
    lb_v = max(-0.95, vd_min / max(vd_pop, 1e-9) - 1.0)
    bounds = [(lb_cl, None), (lb_v, None)]

    def parts(x):
        pred = np.array(tl.concentrations(x[0], x[1], vd_pop))
        o_obs = float(np.sum(((cobs - pred) / sigma) ** 2))
        o_pri = float((x[0] / omega_cl) ** 2 + (x[1] / omega_v) ** 2)
        return o_pri, o_obs, pred

    def objective(x):
        if x[0] <= lb_cl - 1e-9 or x[1] <= lb_v - 1e-9:
            return 1e12
        o_pri, o_obs, _ = parts(x)
        return o_pri + o_obs

    cands = []
    for x0 in ([0.0, 0.0], [0.5, 0.0], [-0.5, 0.0], [0.0, 0.5], [0.0, -0.4], [0.8, 0.5], [-0.6, -0.3]):
        try:
            r = minimize(objective, np.array(x0, float), method="L-BFGS-B", bounds=bounds,
                         options={"maxiter": 500, "ftol": 1e-13})
            if np.isfinite(r.fun):
                cands.append(r)
        except Exception:
            continue
    if not cands:
        return AmgBayesResult(0, 0, 0, 0, 0, False, "Thuật toán tối ưu không hội tụ.")
    best = min(cands, key=lambda r: r.fun)
    try:   # tinh chinh khong dung dao ham (on dinh khi L-BFGS-B dung som)
        r2 = minimize(objective, best.x, method="Nelder-Mead", options={"xatol": 1e-8, "fatol": 1e-12, "maxiter": 2000})
        if np.isfinite(r2.fun) and r2.fun <= best.fun:
            best = r2
    except Exception:
        pass
    eta_cl, eta_v = float(best.x[0]), float(best.x[1])
    o_pri, o_obs, pred = parts(best.x)

    cl_now = tl.cl_pop_now * (1.0 + eta_cl)
    v_now = vd_pop * (1.0 + eta_v)
    assign = {id(a["measurement"]): a for a in assign_measurements_amg(used, ds)}
    points = []
    for m, p in zip(used, pred):
        a = assign[id(m)]
        points.append({"t_obs": m.t_obs, "c_obs": m.c_obs, "c_pred": float(p),
                       "ofv": float(((m.c_obs - p) / sigma) ** 2),
                       "dose_index": a["dose_index"], "in_infusion": a["in_infusion"],
                       "hours_after_end": a["hours_after_end"]})
    last_assign = assign[id(used[-1])]
    return AmgBayesResult(
        CL_optimized=float(cl_now), Vd_optimized=float(v_now), Ke=float(cl_now / v_now),
        C_pred_final=float(pred[-1]), OFV_final=float(o_pri + o_obs), success=True,
        message="Đã hội tụ thành công.", points=points, anchor_dose=last_assign["dose"],
        eta_cl=eta_cl, eta_vd=eta_v, cl_pop_current=float(tl.cl_pop_now), vd_pop=float(vd_pop),
        crcl_current=float(tl.crcl_now), ofv_prior=o_pri, ofv_obs=o_obs, n_used=len(used))


# ==========================================
# 7. CANH BAO PHAM VI AP DUNG CUA MO HINH
# ==========================================

def check_model_applicability_amg(patient: AmgPatientInfo, scr_entries, doses: List[AmgDose],
                                   measurements: List[AmgMeasurement]) -> list:
    """Trả về list (level, text); level: 'warn' | 'info'. Chỉ CẢNH BÁO, không chặn tính toán.
    scr_entries: (SCr mg/dL, thời điểm). Khoảng tham chiếu = AA2020_RANGES (quần thể của bài báo)."""
    R = AA2020_RANGES
    out = []
    ds = sorted(doses, key=lambda d: d.given_at)

    def rng(key):
        lo, hi = R[key]
        return f"{lo:g}–{hi:g}"

    if patient.age < R["age"][0] or patient.age > R["age"][1]:
        out.append(("warn", f"Tuổi {patient.age:g} nằm ngoài khoảng của quần thể xây dựng mô hình ({rng('age')}; trung vị 33,5) — "
                            "bài báo khuyến cáo thận trọng khi ngoại suy sang quần thể khác."))
    if str(patient.gender).lower() not in ("nam", "male", "m"):
        out.append(("info", "Nữ chỉ chiếm ~10% (5/50) bệnh nhân xây dựng mô hình."))
    if patient.weight_kg < R["weight"][0] or patient.weight_kg > R["weight"][1]:
        out.append(("warn", f"Cân nặng {patient.weight_kg:g} kg nằm ngoài khoảng của bài báo ({rng('weight')} kg)."))
    ibw = compute_ibw_amg(patient.gender, patient.height_cm)
    if ibw < R["ibw"][0] or ibw > R["ibw"][1]:
        out.append(("warn", f"IBW {ibw:.1f} kg nằm ngoài khoảng ~{rng('ibw')} kg (68,1 ± 2SD). V quần thể = 20,3×(IBW/68)^2,94 "
                            f"= {compute_vd_prior_amg(ibw):.1f} L rất nhạy với IBW (số mũ 2,94; KTC 95% 1,27–5,40) nên tiên nghiệm V kém chắc chắn."))
    for s, t in sorted(scr_entries, key=lambda e: e[1]):
        if s < R["scr"][0] or s > R["scr"][1]:
            out.append(("warn", f"SCr {s:.2f} mg/dL ({t:%d/%m %H:%M}) ngoài khoảng của bài báo ({rng('scr')} mg/dL)."))
        crcl = compute_crcl_amg(patient.age, patient.gender, patient.weight_kg, s)
        if crcl < R["crcl"][0] or crcl > R["crcl"][1]:
            out.append(("warn", f"CrCl (CG, TBW) = {crcl:.0f} mL/phút ({t:%d/%m %H:%M}) ngoài khoảng ~{rng('crcl')} mL/phút "
                                "(130 ± 2SD của quần thể) — ít dữ liệu ở vùng này."))
    if ds:
        first_scr_t = min(t for _, t in scr_entries) if scr_entries else None
        if first_scr_t is not None and first_scr_t > ds[0].given_at:
            gap = (first_scr_t - ds[0].given_at).total_seconds() / 3600.0
            if gap >= 12:
                out.append(("info", f"SCr đầu tiên đo sau liều đầu {gap:.0f} h: giả định SCr không đổi trước thời điểm đó."))
        for a, b in zip(ds[:-1], ds[1:]):
            gap = (b.given_at - a.given_at).total_seconds() / 3600.0
            if gap < 20:
                out.append(("warn", f"Khoảng cách giữa 2 liều ({a.given_at:%d/%m %H:%M} → {b.given_at:%d/%m %H:%M}) chỉ {gap:.1f} h: "
                                    "mô hình được xây dựng cho liều 1 lần/ngày."))
        for d in ds:
            if d.dose_mg > R["dose_day"][1] * 1.0001 or d.dose_mg < R["dose_day"][0] * 0.9999:
                out.append(("info", f"Liều {d.dose_mg:g} mg ({d.given_at:%d/%m %H:%M}) ngoài khoảng {rng('dose_day')} mg/ngày của bài báo."))
        out.append(("info", "Giả định lịch sử liều đầy đủ từ LIỀU ĐẦU TIÊN của đợt điều trị (không còn thuốc tồn trước liều đầu trong bảng)."))
    assigns = assign_measurements_amg(measurements, ds)
    for a in assigns:
        m = a["measurement"]
        if a["dose_index"] is None:
            out.append(("warn", f"Mẫu Tobs {m.t_obs:%d/%m %H:%M} (Cobs {m.c_obs:g}) nằm TRƯỚC liều đầu tiên — sẽ bị bỏ qua."))
            continue
        n = a["dose_index"] + 1
        if a["in_infusion"]:
            out.append(("warn", f"Mẫu Tobs {m.t_obs:%d/%m %H:%M} (Cobs {m.c_obs:g}) lấy TRONG THỜI GIAN TRUYỀN của liều thứ {n} "
                                f"(sau {a['hours_after_start']:.2f} h / Tinf {a['dose'].t_inf_h:g} h). Vẫn được tính (mô hình liên tục) "
                                "nhưng bài báo chỉ dùng mẫu lấy sau khi kết thúc truyền — kết quả kém tin cậy, nên kiểm tra lại giờ lấy mẫu."))
        elif a["hours_after_end"] < R["post_infusion_min_h"]:
            out.append(("warn", f"Mẫu Tobs {m.t_obs:%d/%m %H:%M} lấy chỉ {a['hours_after_end']*60:.0f} phút sau khi kết thúc truyền liều thứ {n} "
                                "(bài báo: ≥ 30 phút) — có thể còn pha phân bố."))
        elif a["hours_after_start"] > R["post_dose_max_h"] + a["dose"].t_inf_h:
            out.append(("info", f"Mẫu Tobs {m.t_obs:%d/%m %H:%M} lấy {a['hours_after_start']:.1f} h sau liều thứ {n} "
                                f"(bài báo: tối đa ~{R['post_dose_max_h']:g} h)."))
        if m.c_obs < R["cobs"][0] or m.c_obs > R["cobs"][1]:
            out.append(("warn", f"Cobs {m.c_obs:g} µg/mL ({m.t_obs:%d/%m %H:%M}) ngoài thang {rng('cobs')} µg/mL của bài báo."))
    if len([a for a in assigns if a["dose_index"] is not None]) == 1:
        out.append(("info", "Chỉ có 1 điểm đo: kết quả phụ thuộc nhiều vào tiên nghiệm quần thể (cả CL và V đều được ước lượng từ 1 mẫu)."))
    return out


# ==========================================
# 8. Cpeak/Ctrough TRANG THAI ON DINH CUA CHE DO LIEU (du doan lieu moi)
# ==========================================

def compute_css_peak_trough_amg(dose_mg: float, tau_h: float, tinf_h: float, cl: float, vd: float):
    """Cpeak/Ctrough o trang thai on dinh voi lieu+tau+Tinf cho truoc va CL, V CO DINH (CL hien tai)."""
    ke = cl / vd if vd > 0 else 0.0
    if ke <= 0 or tau_h <= 0 or tinf_h <= 0 or cl <= 0:
        return 0.0, 0.0
    cpeak = ((dose_mg / (tinf_h * cl)) * (1 - np.exp(-ke * tinf_h))) / (1 - np.exp(-ke * tau_h))
    ctrough = cpeak * np.exp(-ke * (tau_h - tinf_h))
    return float(cpeak), float(ctrough)

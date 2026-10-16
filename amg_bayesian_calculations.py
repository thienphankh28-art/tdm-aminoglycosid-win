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

PHIEN BAN 16/10/2026: them PHAN 9-12 (DA MO HINH): 7 mo hinh moi (Perez-Blanco 2020, Jin 2020, Illamola 2018,
  Carrie 2020 cho amikacin; Smit 2019, Hodiamont 2017 cho gentamicin; Rea 2008 cho gentamicin + tobramycin),
  bo tinh 1-2 ngan chung, OFV kieu Tucuxi, va ham tu chon mo hinh. Phan 0-8 (Arechiga-Alvarado) GIU NGUYEN.

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
    # --- bo sung v16.10.26 (da mo hinh); mac dinh rong de tuong thich mo hinh Arechiga-Alvarado cu ---
    model_key: str = "AA2020"
    params_now: dict = field(default_factory=dict)   # thong so CA THE hien tai {CL, V1, Q, V2}
    params_pop: dict = field(default_factory=dict)   # thong so QUAN THE hien tai (eta = 0)
    etas: dict = field(default_factory=dict)         # {ten thong so: eta}


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


# =====================================================================================================
# 9. DA MO HINH (v16.10.26) -- HIEP BIEN DUNG CHUNG
#    Moi ham nhan SCr da la mg/dL; can nang kg; chieu cao cm; albumin g/L.
# =====================================================================================================

def _is_male(gender) -> bool:
    return str(gender).strip().lower() in ("nam", "male", "m", "1")


def compute_abw_amg(gender: str, height_cm: float, weight_kg: float) -> float:
    """Can nang hieu chinh ABW = IBW + 0.4 x (TBW - IBW) (IBW Devine)."""
    ibw = compute_ibw_amg(gender, height_cm)
    return ibw + 0.4 * (weight_kg - ibw)


def compute_bsa_dubois(weight_kg: float, height_cm: float) -> float:
    """Dien tich da (m2) theo Du Bois."""
    return 0.007184 * (max(weight_kg, 1e-6) ** 0.425) * (max(height_cm, 1e-6) ** 0.725)


def compute_egfr_ckdepi2009(age: float, gender: str, scr_mgdl: float) -> float:
    """CKD-EPI 2009 (mL/min/1.73 m2), khong he so chung toc."""
    if scr_mgdl <= 0:
        return 0.0
    male = _is_male(gender)
    k = 0.9 if male else 0.7
    a = -0.411 if male else -0.329
    v = 141.0 * (min(scr_mgdl / k, 1.0) ** a) * (max(scr_mgdl / k, 1.0) ** -1.209) * (0.993 ** age)
    return v if male else v * 1.018


def compute_egfr_ckdepi_abs(age: float, gender: str, scr_mgdl: float, weight_kg: float, height_cm: float) -> float:
    """CKD-EPI 2009 BO CHUAN HOA 1.73 m2 (mL/min tuyet doi) = eGFR x BSA/1.73 (Perez-Blanco 2020)."""
    return compute_egfr_ckdepi2009(age, gender, scr_mgdl) * compute_bsa_dubois(weight_kg, height_cm) / 1.73


def compute_egfr_mdrd175(age: float, gender: str, scr_mgdl: float) -> float:
    """MDRD 4 bien (IDMS, 175) mL/min/1.73 m2 -- Jin 2020."""
    if scr_mgdl <= 0 or age <= 0:
        return 0.0
    v = 175.0 * scr_mgdl ** -1.154 * age ** -0.203
    return v if _is_male(gender) else v * 0.742


def compute_gfr_mdrd186(age: float, gender: str, scr_mgdl: float) -> float:
    """MDRD 186 (Rea 2008, cong thuc (1) trong bai): 186.3 x Cr^-1.154 x Tuoi^-0.203 x 0.742 (nu)
    (he so 1.212 cho nguoi da den khong ap dung)."""
    if scr_mgdl <= 0 or age <= 0:
        return 0.0
    v = 186.3 * scr_mgdl ** -1.154 * age ** -0.203
    return v if _is_male(gender) else v * 0.742


@dataclass
class AmgClinicalInfo:
    """Thong tin lam sang bo sung de chon mo hinh va tinh hiep bien (o nhap them o Tab 1)."""
    setting: str = ""                 # "icu" | "ward" | "" (chua chon)
    cf: bool = False                  # xo nang
    ntm: bool = False                 # benh phoi do mycobacteria khong lao
    open_abdomen: bool = False        # bung ho + hut ap luc am (NPT)
    crrt: bool = False                # loc mau lien tuc (CRRT/CVVH)
    vanco: bool = False               # dung kem vancomycin
    albumin_gl: Optional[float] = None    # albumin mau (g/L)
    urine_crcl: Optional[float] = None    # CrCl do tu nuoc tieu 6 h (mL/phut) -- Hodiamont 2017

    def to_dict(self) -> dict:
        return {"setting": self.setting, "cf": self.cf, "ntm": self.ntm, "open_abdomen": self.open_abdomen,
                "crrt": self.crrt, "vanco": self.vanco, "albumin_gl": self.albumin_gl, "urine_crcl": self.urine_crcl}

    @staticmethod
    def from_dict(d) -> "AmgClinicalInfo":
        d = d or {}
        def f(x):
            try:
                return None if x is None or x == "" else float(x)
            except (TypeError, ValueError):
                return None
        return AmgClinicalInfo(setting=str(d.get("setting") or ""), cf=bool(d.get("cf")), ntm=bool(d.get("ntm")),
                               open_abdomen=bool(d.get("open_abdomen")), crrt=bool(d.get("crrt")),
                               vanco=bool(d.get("vanco")), albumin_gl=f(d.get("albumin_gl")),
                               urine_crcl=f(d.get("urine_crcl")))


def build_covariates_amg(patient: AmgPatientInfo, clin: AmgClinicalInfo, scr_mgdl: float) -> dict:
    """Tat ca hiep bien co the can (moi mo hinh chi dung phan cua minh) tai 1 gia tri SCr."""
    g, age, wt, ht = patient.gender, patient.age, patient.weight_kg, patient.height_cm
    ibw = compute_ibw_amg(g, ht)
    return {
        "age": age, "male": _is_male(g), "tbw": wt, "height": ht, "ibw": ibw,
        "abw": ibw + 0.4 * (wt - ibw), "bsa": compute_bsa_dubois(wt, ht), "scr": scr_mgdl,
        "crcl_cg": compute_crcl_amg(age, g, wt, scr_mgdl),
        "egfr_ckdepi_abs": compute_egfr_ckdepi_abs(age, g, scr_mgdl, wt, ht),
        "egfr_mdrd175": compute_egfr_mdrd175(age, g, scr_mgdl),
        "gfr_mdrd186": compute_gfr_mdrd186(age, g, scr_mgdl),
        "albumin_gl": clin.albumin_gl, "vanco": 1.0 if clin.vanco else 0.0, "crrt": clin.crrt,
        "urine_crcl": clin.urine_crcl,
    }


# =====================================================================================================
# 10. DINH NGHIA MO HINH (thong so lay tu bai bao goc -- xem bang_mo_hinh_bayesian_san_sang_2026-10-16.md)
# =====================================================================================================

def _cv_to_omega_lognormal(cv: float) -> float:
    """CV (%) bao cao theo sqrt(exp(w^2)-1) -> SD cua eta."""
    return math.sqrt(math.log(1.0 + cv * cv))


class AmgModelSpec:
    """Mo ta 1 mo hinh PopPK. tv(cov, clin) -> dict thong so dien hinh {CL, V1[, Q, V2]} (L/h, L).
    omega(clin) -> (ten eta, ma tran OMEGA (phuong sai/hiep phuong sai cua eta)).
    bsv: 'exp' (P = TV x exp(eta)) hoac 'prop' (P = TV x (1 + eta)).
    err: 'add' | 'prop' | 'comb' | 'log' voi sigma_add (mg/L hoac thang log) va sigma_prop (ti le)."""

    def __init__(self, key, name, drugs, n_cmt, tv, omega, bsv, err, sigma_add=0.0, sigma_prop=0.0,
                 renal_key=None, needs=(), population="", reference="", ranges=None, notes=()):
        self.key, self.name, self.drugs, self.n_cmt = key, name, tuple(drugs), n_cmt
        self.tv, self.omega, self.bsv, self.err = tv, omega, bsv, err
        self.sigma_add, self.sigma_prop = sigma_add, sigma_prop
        self.renal_key = renal_key          # hiep bien than dung cho CL (bien thien theo SCr), None neu khong co
        self.needs = tuple(needs)           # thong tin bo sung BAT BUOC: 'albumin'
        self.population, self.reference = population, reference
        self.ranges = ranges or {}
        self.notes = tuple(notes)

    @property
    def label(self):
        return f"{self.name} ({self.n_cmt} ngăn)"

    def param_names(self):
        return ["CL", "V1"] if self.n_cmt == 1 else ["CL", "V1", "Q", "V2"]

    def missing_inputs(self, clin: AmgClinicalInfo) -> list:
        out = []
        if "albumin" in self.needs and (clin.albumin_gl is None or clin.albumin_gl <= 0):
            out.append("albumin máu (g/L)")
        return out


def _omega_matrix(sds, corr=None):
    sds = np.asarray(sds, float)
    om = np.diag(sds ** 2)
    for (i, j), r in (corr or {}).items():
        om[i, j] = om[j, i] = r * sds[i] * sds[j]
    return om


# --- 1. Arechiga-Alvarado 2020 (amikacin) -- giu nguyen cach tinh cu (phan 0-8), khai bao o day de chon mo hinh
def _tv_aa(c, clin):
    return {"CL": AA2020_THETA_CL * (max(c["crcl_cg"], 1e-6) / AA2020_CRCL_REF) ** AA2020_EXP_CL,
            "V1": AA2020_THETA_V * (max(c["ibw"], 1e-6) / AA2020_IBW_REF) ** AA2020_EXP_V}


# --- 2. Perez-Blanco 2020 (amikacin; JAC 75:2222)
def _tv_pb(c, clin):
    alb_gdl = (c["albumin_gl"] or 29.0) / 10.0
    cl = (0.525 + 4.78 * c["egfr_ckdepi_abs"] / 98.0) * (1.0 - 0.226 * c["vanco"])
    v = 26.3 * (alb_gdl / 2.9) ** -0.517 * (1.0 + 0.00609 * (c["tbw"] - 70.0))
    return {"CL": cl, "V1": v}


# --- 3. Jin 2020 (amikacin, benh phoi NTM; Antibiotics 9:784)
def _tv_jin(c, clin):
    return {"CL": 3.52 * (max(c["egfr_mdrd175"], 1e-6) / 91.1) ** 0.229,
            "V1": 14.4 * (c["tbw"] / 51.1) ** 0.702, "Q": 0.464, "V2": 14.2}


# --- 4. Illamola 2018 (amikacin, nguoi lon xo nang; AAC 62:e00877-18)
def _tv_ill(c, clin):
    return {"CL": 3.06 + 1.55 * (c["crcl_cg"] / 110.0),
            "V1": 14.4 * (c["tbw"] / 63.0) ** 0.918, "Q": 0.925, "V2": 17.1}


# --- 5. Carrie 2020 (amikacin, ICU bung ho + NPT; AAC 64:e02098-19; Monolix: omega = SD cua eta)
def _tv_car(c, clin):
    if clin.crrt:
        return {"CL": 2.32, "V1": 25.5 * (c["abw"] / 79.6) ** 0.73, "Q": 1.19, "V2": 14.1}
    r = max(c["crcl_cg"], 1e-6) / 66.7
    return {"CL": 3.02 * r ** 0.69, "V1": 23.2 * r ** 0.22 * (c["abw"] / 79.6) ** 0.48, "Q": 1.05, "V2": 11.7}


def _om_car(clin):
    if clin.crrt:
        return ["CL", "V1", "V2", "Q"], _omega_matrix([0.221, 0.081, 0.380, 0.418])
    return ["CL", "V1", "V2", "Q"], _omega_matrix([0.345, 0.047, 0.695, 0.813])


# --- 6. Smit 2019 (gentamicin, beo phi + nguoi khoe, than binh thuong; CL/Q goc L/phut -> x60)
def _tv_smit(c, clin):
    w = c["tbw"] / 70.0
    return {"CL": 0.0892 * 60.0 * w ** 0.729, "V1": 11.9 * w ** 1.25, "Q": 0.0848 * 60.0, "V2": 7.29}


# --- 7. Hodiamont 2017 (gentamicin ICU, co/khong CVVH; moi thong so chuan hoa theo IBW/70)
def _tv_hod(c, clin):
    s = c["ibw"] / 70.0
    alb = c["albumin_gl"] or 22.0
    if clin.crrt:
        cl = 2.13 * s ** 0.75
    elif c["urine_crcl"] is not None and c["urine_crcl"] > 0:
        cl = 1.15 * s ** 0.75 * (1.0 + 0.0131 * (c["urine_crcl"] - 30.0))
    else:
        cl = 1.15 * s ** 0.75 * 1.39          # he so hieu chinh khi KHONG co CrCl nuoc tieu (Eq. 3 bai bao)
    return {"CL": max(cl, 0.05), "V1": 21.2 * s * (alb / 22.0) ** -0.833, "Q": 1.96 * s ** 0.75, "V2": 18.4 * s}


def _om_hod(clin):
    w_cl = _cv_to_omega_lognormal(0.295 if clin.crrt else 0.425)
    w_v1 = _cv_to_omega_lognormal(0.172)
    return ["CL", "V1"], _omega_matrix([w_cl, w_v1], {(0, 1): 0.54})


# --- 8. Rea 2008 (gentamicin + tobramycin, ICU noi khoa; Ther Drug Monit 30:674)
def _tv_rea(c, clin):
    g = max(c["gfr_mdrd186"], 1e-6) ** 1.2
    return {"CL": 3.14 * g / (54.8 ** 1.2 + g), "V1": 53.0 * c["tbw"] / 70.0}


AMIKACIN, GENTAMICIN, TOBRAMYCIN = "amikacin", "gentamicin", "tobramycin"

# NGUONG DINH LUONG (LLOQ, mg/L) = gioi han phat hien cua may do tai benh vien, theo tung thuoc.
# None = CHUA CAU HINH (chua co gia tri tu khoa xet nghiem). Khi da co gia tri: dien so vao day (vd 0.3),
# moi mau Cobs < LLOQ se bi CHAN (khong chay Bayes) vi mau duoi nguong khong co gia tri dinh luong.
AMG_LLOQ_MGL = {AMIKACIN: None, GENTAMICIN: None, TOBRAMYCIN: None}

AMG_MODELS = {
    "AA2020": AmgModelSpec(
        "AA2020", "Aréchiga-Alvarado 2020", [AMIKACIN], 1, _tv_aa,
        lambda clin: (["CL", "V1"], _omega_matrix([AA2020_OMEGA_CL, AA2020_OMEGA_V])), "prop", "add",
        sigma_add=AA2020_SIGMA, renal_key="crcl_cg",
        population="63 BN hồi sức (Mexico), nhiều mức chức năng thận, 50% tăng thanh thải thận; liều 1 lần/ngày",
        reference="Aréchiga-Alvarado NA et al. AAC 2020;64:e02178-19",
        ranges={"age": (18, 67), "weight": (44, 138), "crcl_cg": (49, 211)}),
    "PB2020": AmgModelSpec(
        "PB2020", "Pérez-Blanco 2020", [AMIKACIN], 1, _tv_pb,
        lambda clin: (["CL", "V1"], _omega_matrix([0.283, 0.104])), "exp", "comb",
        sigma_add=1.99, sigma_prop=0.237, renal_key="egfr_ckdepi_abs", needs=("albumin",),
        population="294 BN nội trú (Tây Ban Nha), 75% giảm albumin; liều chủ yếu 1 lần/ngày",
        reference="Pérez-Blanco JS et al. J Antimicrob Chemother 2020;75:2222-31",
        ranges={"age": (18, 93), "weight": (43, 190), "egfr_ckdepi_abs": (17, 194), "albumin_gl": (12, 50)}),
    "JIN2020": AmgModelSpec(
        "JIN2020", "Jin 2020", [AMIKACIN], 2, _tv_jin,
        lambda clin: (["CL", "V1"], _omega_matrix([0.279, 0.18], {(0, 1): -0.0135 / (0.279 * 0.18)})), "exp", "log",
        sigma_add=0.299, renal_key="egfr_mdrd175",
        population="70 BN bệnh phổi NTM (Hàn Quốc), 30–80 kg; liều cao 1 lần/ngày",
        reference="Jin X et al. Antibiotics 2020;9:784",
        ranges={"age": (25, 85), "weight": (29.9, 79.8), "egfr_mdrd175": (26.8, 297.8)}),
    "ILL2018": AmgModelSpec(
        "ILL2018", "Illamola 2018", [AMIKACIN], 2, _tv_ill,
        lambda clin: (["CL"], _omega_matrix([0.20])), "exp", "prop",
        sigma_prop=0.1661, renal_key="crcl_cg",
        population="49 người lớn xơ nang (Mỹ); liều q8h–q24h",
        reference="Illamola SM et al. AAC 2018;62:e00877-18",
        ranges={"age": (18, 70), "crcl_cg": (40, 200)}),
    "CAR2020": AmgModelSpec(
        "CAR2020", "Carrié 2020", [AMIKACIN], 2, _tv_car, _om_car, "exp", "prop",
        sigma_prop=0.132, renal_key="crcl_cg",
        population="70 BN hồi sức bụng hở + hút áp lực âm (Pháp), có/không CRRT; 25–30 mg/kg q24h",
        reference="Carrié C et al. AAC 2020;64:e02098-19"),
    "SMIT2019": AmgModelSpec(
        "SMIT2019", "Smit 2019", [GENTAMICIN], 2, _tv_smit,
        lambda clin: (["CL", "V1"], _omega_matrix([0.181, 0.192], {(0, 1): 0.0316 / (0.181 * 0.192)})), "exp", "comb",
        sigma_add=0.206, sigma_prop=0.159, renal_key=None,
        population="28 người (20 béo phì nặng, 8 khỏe mạnh), chức năng thận BÌNH THƯỜNG; liều đơn 5 mg/kg",
        reference="Smit C et al. Clin Pharmacokinet 2019;58:1333-43",
        ranges={"age": (19, 54), "weight": (53, 221), "crcl_cg": (60, 1e9)}),
    "HOD2017": AmgModelSpec(
        "HOD2017", "Hodiamont 2017", [GENTAMICIN], 2, _tv_hod, _om_hod, "exp", "prop",
        sigma_prop=0.338, renal_key=None, needs=("albumin",),
        population="44 BN hồi sức (Hà Lan), có/không CVVH; khởi đầu 4 mg/kg",
        reference="Hodiamont CJ et al. Int J Antimicrob Agents 2017;49:204-11",
        ranges={"albumin_gl": (10, 36)}),
    "REA2008": AmgModelSpec(
        "REA2008", "Rea 2008", [GENTAMICIN, TOBRAMYCIN], 1, _tv_rea,
        lambda clin: (["CL", "V1"], _omega_matrix([0.837, 0.644])), "exp", "comb",
        sigma_add=0.381, sigma_prop=0.243, renal_key="gfr_mdrd186",
        population="102 BN hồi sức nội khoa (Mỹ), đa số suy thận (GFR TB 48 mL/phút); gentamicin/tobramycin gộp",
        reference="Rea RS et al. Ther Drug Monit 2008;30:674-81",
        ranges={"age": (18, 92), "weight": (29, 222), "gfr_mdrd186": (3.8, 102.5)}),
}

_RANGE_LABEL = {"age": ("Tuổi", ""), "weight": ("Cân nặng", " kg"), "crcl_cg": ("CrCl Cockcroft–Gault", " mL/phút"),
                "egfr_ckdepi_abs": ("eGFR CKD-EPI (tuyệt đối)", " mL/phút"),
                "egfr_mdrd175": ("eGFR MDRD", " mL/phút/1,73 m²"), "gfr_mdrd186": ("GFR MDRD (Rea)", " mL/phút"),
                "albumin_gl": ("Albumin", " g/L")}


def drug_key_amg(drug_label: str) -> str:
    d = str(drug_label).lower()
    for k in (AMIKACIN, GENTAMICIN, TOBRAMYCIN):
        if k in d:
            return k
    return ""


def models_for_drug(drug_label: str) -> list:
    """Danh sach key mo hinh ap dung cho thuoc (theo thu tu hien thi)."""
    dk = drug_key_amg(drug_label)
    return [k for k, m in AMG_MODELS.items() if dk in m.drugs]


def model_key_from_label(label: str) -> str:
    for k, m in AMG_MODELS.items():
        if label in (m.label, m.name, k):
            return k
    return ""


# =====================================================================================================
# 11. BO TINH CHUNG 1-2 NGAN: tich phan theo doan (thong so hang so trong tung doan), OFV kieu Tucuxi
# =====================================================================================================

def _apply_eta(tv: np.ndarray, eta: float, bsv: str) -> np.ndarray:
    return tv * (1.0 + eta) if bsv == "prop" else tv * math.exp(eta)


class AmgMultiTimeline:
    """Luoi thoi gian cho mo hinh bat ky. Thong so dien hinh tinh tai DIEM GIUA moi doan (SCr noi suy tuyen
    tinh giua cac lan do, giu hang so ngoai khoang). Doan chi chia nho trong vung SCr bien thien VA khi mo hinh
    co hiep bien than (renal_key)."""

    def __init__(self, spec: AmgModelSpec, patient: AmgPatientInfo, clin: AmgClinicalInfo, scr_entries,
                 doses: List[AmgDose], eval_times, dt_max: float = 0.5):
        if not doses:
            raise ValueError("Chưa có liều.")
        self.spec, self.patient, self.clin = spec, patient, clin
        ds = sorted(doses, key=lambda d: d.given_at)
        self.doses = ds
        self.t_start = ds[0].given_at
        H = lambda t: (t - self.t_start).total_seconds() / 3600.0
        scr = _sorted_scr(scr_entries)
        scr_h = np.array([H(t) for _, t in scr])
        scr_v = np.array([s for s, _ in scr])
        self.scr_last = float(scr_v[-1])
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
        var_lo, var_hi = float(scr_h[0]), float(scr_h[-1])
        varying = spec.renal_key is not None and len(scr_h) > 1
        starts, dts, rates, scrs = [], [], [], []
        for a, b in zip(bps[:-1], bps[1:]):
            if b - a <= 1e-12:
                continue
            n = max(1, int(math.ceil((b - a) / dt_max))) if (varying and b > var_lo and a < var_hi) else 1
            step = (b - a) / n
            for j in range(n):
                s0 = a + j * step
                mid = s0 + step / 2.0
                rate = 0.0
                for d in ds:
                    d0 = H(d.given_at)
                    if d0 <= mid < d0 + float(d.t_inf_h):
                        rate += d.dose_mg / float(d.t_inf_h)
                starts.append(s0)
                dts.append(step)
                rates.append(rate)
                scrs.append(float(np.interp(mid, scr_h, scr_v)))
        self.starts, self.dts, self.rates = np.array(starts), np.array(dts), np.array(rates)
        self.ends = self.starts + self.dts
        # thong so dien hinh theo doan (cache theo gia tri SCr)
        cache = {}
        names = spec.param_names()
        tvs = {n: [] for n in names}
        self.renal_vals = []
        for s in scrs:
            key = round(s, 6)
            if key not in cache:
                cov = build_covariates_amg(patient, clin, s)
                cache[key] = (spec.tv(cov, clin), cov.get(spec.renal_key) if spec.renal_key else None)
            p, rv = cache[key]
            for n in names:
                tvs[n].append(p[n])
            self.renal_vals.append(rv)
        self.tv = {n: np.array(v, float) for n, v in tvs.items()}
        self.eval_idx = [(-1 if (h <= 0 or len(self.ends) == 0) else int(np.argmin(np.abs(self.ends - h))))
                         for h in eval_h]
        cov_now = build_covariates_amg(patient, clin, self.scr_last)
        self.cov_now = cov_now
        self.tv_now = spec.tv(cov_now, clin)
        self.renal_now = cov_now.get(spec.renal_key) if spec.renal_key else None

    def individual_params(self, etas: dict) -> dict:
        out = {}
        for n, arr in self.tv.items():
            e = etas.get(n, 0.0)
            out[n] = _apply_eta(arr, e, self.spec.bsv) if e else arr
        return out

    def concentrations(self, etas: dict) -> List[float]:
        P = self.individual_params(etas)
        cl, v1 = P["CL"], P["V1"]
        if np.any(cl <= 0) or np.any(v1 <= 0):
            return [float("nan")] * len(self.eval_h)
        dt, R = self.dts, self.rates
        n = len(dt)
        if n == 0:
            return [0.0] * len(self.eval_h)
        if self.spec.n_cmt == 1:
            k = cl / v1
            phi = np.exp(-k * dt)
            g = R * (1.0 - phi) / k
            a = 0.0
            amt = np.empty(n)
            phl, gl = phi.tolist(), g.tolist()
            for i in range(n):
                a = a * phl[i] + gl[i]
                amt[i] = a
            c1 = amt / v1
        else:
            q, v2 = P["Q"], P["V2"]
            if np.any(q <= 0) or np.any(v2 <= 0):
                return [float("nan")] * len(self.eval_h)
            k10, k12, k21 = cl / v1, q / v1, q / v2
            m11, m12, m21, m22 = -(k10 + k12), k21, k12, -k21
            tr = m11 + m22
            det = m11 * m22 - m12 * m21                      # = k10*k21 > 0
            disc = np.sqrt(np.maximum(tr * tr - 4 * det, 1e-300))
            l1, l2 = (tr + disc) / 2.0, (tr - disc) / 2.0   # am, l1 > l2
            e1, e2 = np.exp(l1 * dt), np.exp(l2 * dt)
            dl = l1 - l2
            # Phi = [e1 (M - l2 I) - e2 (M - l1 I)] / (l1 - l2)
            p11 = (e1 * (m11 - l2) - e2 * (m11 - l1)) / dl
            p12 = (e1 - e2) * m12 / dl
            p21 = (e1 - e2) * m21 / dl
            p22 = (e1 * (m22 - l2) - e2 * (m22 - l1)) / dl
            # g = M^-1 (Phi - I) [R, 0]
            a11, a21 = p11 - 1.0, p21
            g1 = R * (m22 * a11 - m12 * a21) / det
            g2 = R * (-m21 * a11 + m11 * a21) / det
            x1 = x2 = 0.0
            amt = np.empty(n)
            P11, P12, P21, P22 = p11.tolist(), p12.tolist(), p21.tolist(), p22.tolist()
            G1, G2 = g1.tolist(), g2.tolist()
            for i in range(n):
                x1, x2 = P11[i] * x1 + P12[i] * x2 + G1[i], P21[i] * x1 + P22[i] * x2 + G2[i]
                amt[i] = x1
            c1 = amt / v1
        return [0.0 if idx < 0 else float(c1[idx]) for idx in self.eval_idx]


def _residual_terms(spec: AmgModelSpec, cobs: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Tung so hang quan sat cua -2LL: r^2/var + ln(var) (giong Tucuxi, bo hang so 2*pi)."""
    pred = np.asarray(pred, float)
    if np.any(~np.isfinite(pred)):
        return np.full(len(cobs), 1e6)
    if spec.err == "log":
        p = np.maximum(pred, 1e-6)
        o = np.maximum(cobs, 1e-6)
        r = np.log(o) - np.log(p)
        var = np.full(len(cobs), spec.sigma_add ** 2)
    else:
        r = cobs - pred
        if spec.err == "add":
            var = np.full(len(cobs), spec.sigma_add ** 2)
        elif spec.err == "prop":
            var = (spec.sigma_prop * np.maximum(pred, 1e-6)) ** 2
        else:
            var = spec.sigma_add ** 2 + (spec.sigma_prop * np.maximum(pred, 0.0)) ** 2
    return r * r / var + np.log(var)


def solve_bayesian_multi(model_key: str, patient: AmgPatientInfo, clin: AmgClinicalInfo, scr_entries,
                         doses: List[AmgDose], measurements: List[AmgMeasurement]) -> AmgBayesResult:
    """MAP Bayes cho mo hinh bat ky trong AMG_MODELS (tru AA2020 da co ham rieng -- van chay duoc qua day).
    OFV = SUM_i [ r_i^2/var_i + ln var_i ] + eta' OMEGA^-1 eta  (= 2 x ham muc tieu cua Tucuxi, bo hang so)."""
    spec = AMG_MODELS.get(model_key)
    fail = lambda msg: AmgBayesResult(0, 0, 0, 0, 0, False, msg, model_key=model_key)
    if spec is None:
        return fail(f"Không có mô hình {model_key}.")
    if not doses:
        return fail("Chưa có dữ liệu lịch sử liều dùng.")
    if not measurements:
        return fail("Chưa có điểm đo Cobs/Tobs nào.")
    miss = spec.missing_inputs(clin)
    if miss:
        return fail(f"Mô hình {spec.name} cần thêm: {', '.join(miss)}.")
    try:
        _sorted_scr(scr_entries)
    except ValueError as e:
        return fail(str(e))
    ds = sorted(doses, key=lambda d: d.given_at)
    if any(d.t_inf_h <= 0 or d.dose_mg <= 0 for d in ds):
        return fail("Mỗi liều phải có liều (mg) > 0 và thời gian truyền > 0.")
    used = sorted([m for m in measurements if m.t_obs > ds[0].given_at], key=lambda m: m.t_obs)
    if not used:
        return fail("Mọi điểm đo (Tobs) đều nằm trước liều đầu tiên.")
    names, omega = spec.omega(clin)
    om_inv = np.linalg.inv(omega)
    sd = np.sqrt(np.diag(omega))
    tl = AmgMultiTimeline(spec, patient, clin, scr_entries, ds, [m.t_obs for m in used])
    cobs = np.array([m.c_obs for m in used], float)

    bounds = [((max(-5 * s, -0.95) if spec.bsv == "prop" else -5 * s), 5 * s) for s in sd]

    def parts(x):
        etas = dict(zip(names, x))
        pred = np.array(tl.concentrations(etas))
        o_obs = float(np.sum(_residual_terms(spec, cobs, pred)))
        xv = np.asarray(x, float)
        o_pri = float(xv @ om_inv @ xv)
        return o_pri, o_obs, pred

    def objective(x):
        for xi, (b0, b1) in zip(x, bounds):
            if xi < b0 - 1e-9 or xi > b1 + 1e-9:
                return 1e12
        o_pri, o_obs, _ = parts(x)
        v = o_pri + o_obs
        return v if np.isfinite(v) else 1e12

    k = len(names)
    starts = [np.zeros(k)]
    for sgn in (1.0, -1.0):
        x0 = np.zeros(k)
        x0[0] = sgn * sd[0]
        starts.append(x0)
    cands = []
    for x0 in starts:
        try:
            r = minimize(objective, x0, method="L-BFGS-B", bounds=bounds,
                         options={"maxiter": 500, "ftol": 1e-13, "gtol": 1e-9})
            if np.isfinite(r.fun):
                cands.append(r)
        except Exception:
            continue
    if not cands:
        return fail("Thuật toán tối ưu không hội tụ.")
    best = min(cands, key=lambda r: r.fun)
    try:
        r2 = minimize(objective, best.x, method="Nelder-Mead",
                      options={"xatol": 1e-8, "fatol": 1e-12, "maxiter": 4000 * k})
        if np.isfinite(r2.fun) and r2.fun <= best.fun:
            best = r2
    except Exception:
        pass
    x = np.asarray(best.x, float)
    o_pri, o_obs, pred = parts(x)
    etas = dict(zip(names, (float(v) for v in x)))
    pop_now = {n: float(v) for n, v in tl.tv_now.items()}
    ind_now = {n: float(_apply_eta(np.array([v]), etas.get(n, 0.0), spec.bsv)[0]) for n, v in pop_now.items()}
    terms = _residual_terms(spec, cobs, pred)
    assign = {id(a["measurement"]): a for a in assign_measurements_amg(used, ds)}
    points = []
    for m, p, t in zip(used, pred, terms):
        a = assign[id(m)]
        points.append({"t_obs": m.t_obs, "c_obs": m.c_obs, "c_pred": float(p), "ofv": float(t),
                       "dose_index": a["dose_index"], "in_infusion": a["in_infusion"],
                       "hours_after_end": a["hours_after_end"]})
    last_assign = assign[id(used[-1])]
    cl, v1 = ind_now["CL"], ind_now["V1"]
    return AmgBayesResult(
        CL_optimized=cl, Vd_optimized=v1, Ke=cl / v1, C_pred_final=float(pred[-1]),
        OFV_final=float(o_pri + o_obs), success=True, message="Đã hội tụ thành công.", points=points,
        anchor_dose=last_assign["dose"], eta_cl=etas.get("CL", 0.0), eta_vd=etas.get("V1", 0.0),
        cl_pop_current=pop_now["CL"], vd_pop=pop_now["V1"],
        crcl_current=float(tl.renal_now) if tl.renal_now is not None else 0.0,
        ofv_prior=o_pri, ofv_obs=o_obs, n_used=len(used),
        model_key=model_key, params_now=ind_now, params_pop=pop_now, etas=etas)


def predict_concentrations_multi(model_key: str, patient: AmgPatientInfo, clin: AmgClinicalInfo, scr_entries,
                                 doses: List[AmgDose], times, etas: Optional[dict] = None) -> List[float]:
    """Nong do du doan tai cac thoi diem (etas=None -> tien nghiem quan the)."""
    spec = AMG_MODELS[model_key]
    tl = AmgMultiTimeline(spec, patient, clin, scr_entries, doses, list(times))
    return tl.concentrations(etas or {})


def simulate_concentration_curve_multi(model_key: str, patient: AmgPatientInfo, clin: AmgClinicalInfo, scr_entries,
                                       doses: List[AmgDose], etas: dict, t_end: datetime.datetime, n_points: int = 300):
    if not doses:
        return [], []
    t_start = min(d.given_at for d in doses)
    total_h = (t_end - t_start).total_seconds() / 3600.0
    if total_h <= 0:
        return [], []
    times = [t_start + datetime.timedelta(hours=float(h)) for h in np.linspace(0, total_h, n_points)]
    return times, predict_concentrations_multi(model_key, patient, clin, scr_entries, doses, times, etas)


def _phi_and_input(params: dict, n_cmt: int, dt: float, rate: float):
    """Ma tran chuyen trang thai Phi(dt) va vecto nap g (luong) cho 1 doan hang so."""
    cl, v1 = params["CL"], params["V1"]
    if n_cmt == 1:
        k = cl / v1
        ph = math.exp(-k * dt)
        return np.array([[ph]]), np.array([rate * (1 - ph) / k])
    q, v2 = params["Q"], params["V2"]
    M = np.array([[-(cl + q) / v1, q / v2], [q / v1, -q / v2]])
    tr, det = M[0, 0] + M[1, 1], M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]
    disc = math.sqrt(max(tr * tr - 4 * det, 1e-300))
    l1, l2 = (tr + disc) / 2, (tr - disc) / 2
    I = np.eye(2)
    Phi = (math.exp(l1 * dt) * (M - l2 * I) - math.exp(l2 * dt) * (M - l1 * I)) / (l1 - l2)
    g = np.linalg.solve(M, (Phi - I) @ np.array([rate, 0.0]))
    return Phi, g


def compute_css_peak_trough_multi(params: dict, n_cmt: int, dose_mg: float, tau_h: float, tinf_h: float):
    """Cpeak (cuoi truyen) / Ctrough (truoc lieu ke) o TRANG THAI ON DINH, thong so CO DINH, 1 hoac 2 ngan."""
    if dose_mg <= 0 or tau_h <= 0 or tinf_h <= 0 or tinf_h > tau_h:
        return 0.0, 0.0
    if params.get("CL", 0) <= 0 or params.get("V1", 0) <= 0:
        return 0.0, 0.0
    Pa, ga = _phi_and_input(params, n_cmt, tinf_h, dose_mg / tinf_h)
    Pb, gb = _phi_and_input(params, n_cmt, tau_h - tinf_h, 0.0)
    P = Pb @ Pa
    g = Pb @ ga + gb
    I = np.eye(P.shape[0])
    x0 = np.linalg.solve(I - P, g)          # luong o dau moi khoang dua lieu (ngay truoc lieu = trough)
    x_peak = Pa @ x0 + ga
    v1 = params["V1"]
    return float(x_peak[0] / v1), float(x0[0] / v1)


# =====================================================================================================
# 12. TU CHON MO HINH + CANH BAO PHAM VI
# =====================================================================================================

def recommend_model_amg(drug_label: str, patient: AmgPatientInfo, clin: AmgClinicalInfo,
                        scr_mgdl: Optional[float] = None):
    """Tra ve (key hoac None, ly do, danh sach thong tin con thieu). None = chua du thong tin de tu chon
    -> nguoi dung tu chon mo hinh."""
    dk = drug_key_amg(drug_label)
    if dk == TOBRAMYCIN:
        why = "Tobramycin: Rea 2008 là mô hình duy nhất đủ tham số (gộp gentamicin/tobramycin, BN hồi sức)."
        if clin.setting != "icu":
            why += " Lưu ý: quần thể gốc là BN hồi sức nội khoa."
        return "REA2008", why, []
    if dk == AMIKACIN:
        if clin.cf:
            return "ILL2018", "Người lớn xơ nang → Illamola 2018 (quần thể xơ nang).", []
        if clin.ntm:
            return "JIN2020", "Bệnh phổi NTM → Jin 2020 (quần thể NTM, liều cao 1 lần/ngày).", []
        if clin.open_abdomen:
            return "CAR2020", "Bụng hở + hút áp lực âm → Carrié 2020" + (" (nhánh CRRT)." if clin.crrt else "."), []
        if clin.setting == "icu":
            if clin.crrt:
                return "CAR2020", ("Hồi sức có lọc máu liên tục → Carrié 2020 nhánh CRRT (mô hình duy nhất có tham số "
                                   "riêng cho CRRT; quần thể gốc là BN bụng hở)."), []
            return "AA2020", "Hồi sức → Aréchiga-Alvarado 2020 (BN hồi sức, gồm tăng thanh thải thận).", []
        if clin.setting == "ward":
            if clin.albumin_gl is None or clin.albumin_gl <= 0:
                return None, ("Nội trú ngoài hồi sức → cần albumin máu để dùng Pérez-Blanco 2020. "
                              "Hãy nhập albumin hoặc tự chọn mô hình."), ["albumin máu (g/L)"]
            return "PB2020", "Nội trú ngoài hồi sức có albumin → Pérez-Blanco 2020.", []
        return None, "Chưa chọn bối cảnh điều trị (hồi sức / ngoài hồi sức) — hãy chọn hoặc tự chọn mô hình.", \
            ["bối cảnh điều trị"]
    if dk == GENTAMICIN:
        has_alb = clin.albumin_gl is not None and clin.albumin_gl > 0
        if clin.crrt:
            if not has_alb:
                return None, ("Lọc máu liên tục → Hodiamont 2017 (có nhánh CVVH) cần albumin máu. "
                              "Hãy nhập albumin hoặc tự chọn mô hình."), ["albumin máu (g/L)"]
            return "HOD2017", "Hồi sức có lọc máu liên tục → Hodiamont 2017 (nhánh CVVH).", []
        if clin.setting == "icu":
            has_ucrcl = clin.urine_crcl is not None and clin.urine_crcl > 0
            if has_alb and has_ucrcl:
                return "HOD2017", "Hồi sức có albumin + CrCl nước tiểu 6 giờ → Hodiamont 2017.", []
            # Kiem thu 16/10: thieu CrCl nuoc tieu thi CL cua Hodiamont co dinh, khong theo SCr -> du doan sai khi
            # chuc nang than thay doi (vd. suy than cap) -> uu tien Rea 2008 (CL theo GFR tu SCr)
            return "REA2008", ("Hồi sức → Rea 2008 (CL theo GFR tính từ SCr). Hodiamont 2017 chỉ được tự chọn khi có cả "
                               "albumin và CrCl đo nước tiểu 6 giờ (thiếu CrCl nước tiểu thì CL của Hodiamont không theo "
                               "chức năng thận)."), []
        if clin.setting == "ward":
            if scr_mgdl is None or scr_mgdl <= 0:
                return None, "Cần ít nhất 1 lần đo SCr để đánh giá chức năng thận.", ["SCr"]
            crcl = compute_crcl_amg(patient.age, patient.gender, patient.weight_kg, scr_mgdl)
            if crcl >= 60:
                return "SMIT2019", (f"Ngoài hồi sức, CrCl {crcl:.0f} mL/phút (chức năng thận bình thường) → Smit 2019 "
                                    "(phù hợp cả người béo phì)."), []
            return "REA2008", (f"Ngoài hồi sức nhưng CrCl {crcl:.0f} mL/phút < 60 → Rea 2008 (không có mô hình "
                                "ngoài hồi sức cho suy thận; quần thể gốc là hồi sức)."), []
        return None, "Chưa chọn bối cảnh điều trị (hồi sức / ngoài hồi sức) — hãy chọn hoặc tự chọn mô hình.", \
            ["bối cảnh điều trị"]
    return None, "Chưa xác định được thuốc.", []


def check_model_applicability_multi(model_key: str, patient: AmgPatientInfo, clin: AmgClinicalInfo, scr_entries,
                                    doses: List[AmgDose], measurements: List[AmgMeasurement]) -> list:
    """Canh bao (level, text) cho mo hinh moi: pham vi hiep bien, quan the, du lieu dau vao."""
    spec = AMG_MODELS[model_key]
    out = [("info", f"Mô hình {spec.label}: {spec.population}. Nguồn: {spec.reference}.")]
    for miss in spec.missing_inputs(clin):
        out.append(("warn", f"Thiếu {miss} — bắt buộc cho mô hình này."))
    rng = spec.ranges
    if "age" in rng and not (rng["age"][0] <= patient.age <= rng["age"][1]):
        out.append(("warn", f"Tuổi {patient.age:g} ngoài khoảng của quần thể gốc ({rng['age'][0]:g}–{rng['age'][1]:g})."))
    if "weight" in rng and not (rng["weight"][0] <= patient.weight_kg <= rng["weight"][1]):
        out.append(("warn", f"Cân nặng {patient.weight_kg:g} kg ngoài khoảng của quần thể gốc "
                            f"({rng['weight'][0]:g}–{rng['weight'][1]:g} kg)."))
    if "albumin_gl" in rng and clin.albumin_gl:
        lo, hi = rng["albumin_gl"]
        if not lo <= clin.albumin_gl <= hi:
            out.append(("warn", f"Albumin {clin.albumin_gl:g} g/L ngoài khoảng của quần thể gốc ({lo:g}–{hi:g} g/L)."))
    rk = spec.renal_key
    for s, t in sorted(scr_entries, key=lambda e: e[1]):
        cov = build_covariates_amg(patient, clin, s)
        for key in ("crcl_cg", "egfr_ckdepi_abs", "egfr_mdrd175", "gfr_mdrd186"):
            if key in rng and (key == rk or key == "crcl_cg"):
                lo, hi = rng[key]
                if not lo <= cov[key] <= hi:
                    lab, unit = _RANGE_LABEL[key]
                    hi_txt = f"{hi:g}" if hi < 1e8 else "∞"
                    out.append(("warn", f"{lab} = {cov[key]:.0f}{unit} (SCr {s:.2f} mg/dL, {t:%d/%m %H:%M}) ngoài khoảng "
                                        f"quần thể gốc ({lo:g}–{hi_txt}{unit})."))
    if model_key == "SMIT2019":
        out.append(("info", "Smit 2019 KHÔNG có hiệp biến chức năng thận (quần thể thận bình thường): SCr chỉ dùng để "
                            "kiểm tra phạm vi, không ảnh hưởng CL quần thể."))
    if model_key == "HOD2017":
        if clin.crrt:
            out.append(("info", "Đang dùng nhánh CVVH của Hodiamont 2017 (CL không phụ thuộc chức năng thận)."))
        elif clin.urine_crcl is None:
            out.append(("warn", "Hodiamont 2017 dùng CrCl đo từ nước tiểu 6 giờ. Chưa nhập → CL quần thể = "
                                "1,15 × 1,39 × (IBW/70)^0,75 cố định, KHÔNG theo SCr; chỉ nồng độ đo mới điều chỉnh CL."))
    if model_key == "REA2008":
        out.append(("info", "Rea 2008: bỏ qua biến thiên giữa các lần (IOV) của V 40,9% vì khớp 1 đợt điều trị; "
                            "GFR tính theo MDRD 186 như bài báo (không dùng hệ số người da đen)."))
    if model_key == "CAR2020" and not clin.open_abdomen:
        out.append(("warn", "Carrié 2020 xây dựng trên BN bụng hở + hút áp lực âm — đang áp dụng ngoài quần thể gốc."))
    if model_key == "ILL2018" and not clin.cf:
        out.append(("warn", "Illamola 2018 xây dựng trên người lớn XƠ NANG — đang áp dụng ngoài quần thể gốc."))
    if model_key == "JIN2020" and not clin.ntm:
        out.append(("warn", "Jin 2020 xây dựng trên BN bệnh phổi NTM — đang áp dụng ngoài quần thể gốc."))
    if model_key == "PB2020" and clin.setting == "icu":
        out.append(("info", "Pérez-Blanco 2020 xây dựng chủ yếu trên BN nội trú ngoài hồi sức."))
    ds = sorted(doses, key=lambda d: d.given_at)
    out.extend(check_dose_overlap_amg(ds))
    if ds:
        first_scr_t = min(t for _, t in scr_entries) if scr_entries else None
        if spec.renal_key and first_scr_t is not None and first_scr_t > ds[0].given_at:
            gap = (first_scr_t - ds[0].given_at).total_seconds() / 3600.0
            if gap >= 12:
                out.append(("info", f"SCr đầu tiên đo sau liều đầu {gap:.0f} h: giả định SCr không đổi trước thời điểm đó."))
        out.append(("info", "Giả định lịch sử liều đầy đủ từ LIỀU ĐẦU TIÊN của đợt điều trị."))
    assigns = assign_measurements_amg(measurements, ds)
    for a in assigns:
        m = a["measurement"]
        if a["dose_index"] is None:
            out.append(("warn", f"Mẫu Tobs {m.t_obs:%d/%m %H:%M} nằm TRƯỚC liều đầu tiên — sẽ bị bỏ qua."))
        elif a["in_infusion"]:
            out.append(("warn", f"Mẫu Tobs {m.t_obs:%d/%m %H:%M} lấy TRONG thời gian truyền liều thứ {a['dose_index'] + 1} "
                                "— vẫn tính nhưng kém tin cậy."))
    if len([a for a in assigns if a["dose_index"] is not None]) == 1:
        out.append(("info", "Chỉ có 1 điểm đo: kết quả phụ thuộc nhiều vào tiên nghiệm quần thể."))
    return out


def fit_diagnostics_amg(model_key: str, clin: AmgClinicalInfo, result: AmgBayesResult) -> list:
    """Kiem tra SAU khi khop (moi mo hinh, ke ca AA2020): eta bat thuong / cham bien, phan du lon,
    nong do rat thap. Tra ve list (level, text). Them tu dot kiem thu benh nhan gia dinh 16/10/2026."""
    out = []
    if result is None or not result.success:
        return out
    spec = AMG_MODELS.get(model_key)
    if spec is None:
        return out
    names, om = spec.omega(clin)
    sd = dict(zip(names, np.sqrt(np.diag(om))))
    etas = result.etas or {"CL": result.eta_cl, "V1": result.eta_vd}
    lab = {"CL": "CL", "V1": "V" if spec.n_cmt == 1 else "V1", "Q": "Q", "V2": "V2"}
    for n, e in etas.items():
        s = sd.get(n)
        if not s:
            continue
        at_bound = abs(e) >= 4.99 * s or (spec.bsv == "prop" and e <= -0.94)
        if at_bound:
            out.append(("warn", f"η_{lab.get(n, n)} = {e:+.2f} chạm GIỚI HẠN tìm kiếm: nồng độ đo không phù hợp mô hình. "
                                "Kết quả KHÔNG đáng tin — kiểm tra đơn vị nồng độ (mg/L), giờ lấy mẫu, liều và thời gian truyền."))
        elif abs(e) > 3.0 * s:
            out.append(("warn", f"η_{lab.get(n, n)} = {e:+.2f} (> 3 lần độ lệch chuẩn quần thể {s:.2f}): bệnh nhân khác xa "
                                "quần thể của mô hình — kiểm tra dữ liệu nhập hoặc cân nhắc mô hình khác."))
    for i, p in enumerate(result.points):
        co, cp = p["c_obs"], p["c_pred"]
        if co > 0 and abs(co - cp) > max(2.0, 0.5 * co):
            out.append(("warn", f"Mẫu {i + 1} ({p['t_obs']:%d/%m %H:%M}): Cobs {co:g} nhưng sau khớp dự đoán {cp:.2f} mg/L "
                                "(lệch > 50%) — có thể sai giờ lấy mẫu/đơn vị, hoặc mô hình không phù hợp."))
        if 0 < co < 0.3:
            out.append(("warn", f"Mẫu {i + 1}: Cobs {co:g} mg/L rất thấp — có thể dưới ngưỡng định lượng của máy đo. "
                                "Ngưỡng định lượng CHƯA được cấu hình nên phần mềm chưa chặn được; nếu mẫu này dưới "
                                "ngưỡng, hãy xóa mẫu và chạy lại."))
    return out


def check_dose_overlap_amg(doses: List[AmgDose]) -> list:
    """Canh bao lieu chong lan thoi gian truyen / trung gio (thuong do nhap sai)."""
    out = []
    ds = sorted(doses, key=lambda d: d.given_at)
    for i, (a, b) in enumerate(zip(ds[:-1], ds[1:])):
        gap = (b.given_at - a.given_at).total_seconds() / 3600.0
        if gap <= 0:
            out.append(("warn", f"Liều thứ {i + 1} và {i + 2} cùng thời điểm bắt đầu ({a.given_at:%d/%m %H:%M}) — kiểm tra nhập trùng."))
        elif gap < a.t_inf_h:
            out.append(("warn", f"Liều thứ {i + 2} bắt đầu khi liều thứ {i + 1} còn đang truyền (Tinf {a.t_inf_h:g} h > "
                                f"khoảng cách {gap:.2f} h) — kiểm tra thời gian truyền."))
    return out


def get_lloq_amg(drug_label: str) -> Optional[float]:
    """LLOQ (mg/L) cua thuoc, None neu chua cau hinh."""
    v = AMG_LLOQ_MGL.get(drug_key_amg(drug_label))
    return float(v) if v is not None and float(v) > 0 else None


def check_below_lloq_amg(drug_label: str, measurements: List[AmgMeasurement]):
    """Tra ve (lloq, [mau duoi nguong]). lloq None -> chua cau hinh, khong chan duoc."""
    lloq = get_lloq_amg(drug_label)
    if lloq is None:
        return None, []
    return lloq, [m for m in measurements if m.c_obs < lloq]

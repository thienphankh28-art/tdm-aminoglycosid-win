# -*- coding: utf-8 -*-
"""
tucuxi_engine.py — Bản chạy Python "như Tucuxi" cho vancomycin 2 ngăn (không cần tucucli).

Đọc TRỰC TIẾP các file mô hình .tdd của Tucuxi (goti2018, colin2019, thomson2009, yamamoto2009)
và mô phỏng cách Tucuxi-core tính (đã đối chiếu mã nguồn tucuxi-core):
  • Hiệp biến: lưới làm mới 1 ngày, neo tại (mốc sớm nhất của yêu cầu − 25 ngày [= 100 chu kỳ bán thải, 6 h]);
    SCr nội suy TUYẾN TÍNH giữa các lần đo (trước lần đầu / sau lần cuối: giữ nguyên giá trị);
    tuổi = số năm nguyên tính từ ngày sinh; clcr = Cockcroft–Gault General do chính Tucuxi tính từ creatinine (µmol/L).
  • Tham số mỗi liều lấy theo bộ tham số hiệu lực TẠI THỜI ĐIỂM BẮT ĐẦU liều (CL đổi theo ngày, V1/V2/Q theo hiệp biến).
  • Bayes MAP với MỘT bộ η duy nhất cho TOÀN BỘ lịch sử:  J(η) = ½·Σ η²/sd² + Σ[ ½ln2π + lnσ + ½(y−f)²/σ² ],
    σ = sqrt(a² + (b·f)²) (mixed) hoặc b·f (proportional). Giá trị trong thẻ <stdDev> của .tdd được dùng NGUYÊN
    như độ lệch chuẩn (đúng như Tucuxi) — kể cả khi bản chất là phương sai (xem ghi chú Colin 2019).
  • BSV: exponential/lognormal  P = TV·exp(η);  proportional  P = TV·(1+η);  none: không có η.
Không sửa file .tdd. Mô hình mới chỉ cần thả thêm file .tdd 2 ngăn dạng truyền tĩnh mạch.
"""
from __future__ import annotations

import datetime
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize

TD = datetime.timedelta
SECURE_START_H = 600.0          # 100 × t½(6 h) — "fantom" start của Tucuxi (halfLife·multiplier trong .tdd)

MODEL_FILES = {
    "tucuxi.goti": "ch.tucuxi.vancomycin.goti2018.tdd",
    "tucuxi.collin": "ch.tucuxi.vancomycin.colin2019.tdd",
    "tucuxi.thomson": "ch.tucuxi.vancomycin.thomson2009.tdd",
    "tucuxi.yamamoto": "ch.tucuxi.vancomycin.yamamoto2009.tdd",
}
MODEL_LABELS = {
    "tucuxi.goti": "tucuxi.goti",
    "tucuxi.collin": "tucuxi.collin",
    "tucuxi.thomson": "tucuxi.thomson",
    "tucuxi.yamamoto": "tucuxi.yamamoto",
}
DEFAULT_DRUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tucuxi_models")


# ---------------------------------------------------------------------------------------------
# 1. Chuyển mã JS nhỏ (tiny-js) trong .tdd sang hàm Python
# ---------------------------------------------------------------------------------------------
def _split_stmts(code: str) -> List[str]:
    return [s.strip() for s in code.replace("\r", "").split(";") if s.strip()]


def _translate_expr(e: str) -> str:
    e = re.sub(r"\bMath\.(pow|exp|log10|log|sqrt|abs|min|max)\b", r"math.\1", e)
    e = e.replace("math.pow(", "pow(").replace("&&", " and ").replace("||", " or ")
    e = re.sub(r"!(?!=)", " not ", e)
    return e


def compile_js(code: str, input_ids: List[str]) -> Callable[..., float]:
    """Dịch đoạn mã (gán, if/else, return) thành hàm Python f(**inputs)."""
    lines: List[str] = []
    for st in _split_stmts(code):
        st = re.sub(r"\s+", " ", st)
        if st.startswith("if"):
            m = re.match(r"if\s*\((.*)\)\s*(.*)$", st)
            cond, body = m.group(1), m.group(2)
            lines.append(f"if {_translate_expr(cond)}:")
            lines.append("    " + _translate_expr(body) if body else "    pass")
        elif st.startswith("else"):
            body = st[4:].strip()
            lines.append("else:")
            lines.append("    " + _translate_expr(body) if body else "    pass")
        elif st.startswith("return"):
            lines.append(_translate_expr(st))
        else:
            lines.append(_translate_expr(st))
    # Thân hàm; dòng đơn "x = 1" sau if/else đã có thụt lề riêng
    body = "\n".join("    " + ln for ln in lines)
    src = f"def _f({', '.join(input_ids)}):\n{body}\n"
    ns = {"math": math}
    exec(compile(src, "<tdd>", "exec"), ns)
    return ns["_f"]


# ---------------------------------------------------------------------------------------------
# 2. Đọc .tdd
# ---------------------------------------------------------------------------------------------
@dataclass
class TuParam:
    id: str
    std: float
    inputs: List[str]
    func: Optional[Callable]
    bsv_type: str            # exponential | proportional | none
    sd: float                # giá trị <stdDev> (dùng nguyên như SD)


@dataclass
class TuCov:
    id: str
    ctype: str               # standard | ageInYears | ageInDays | sex ...
    default: float
    interp: str
    refresh_d: Optional[float]
    hard: Optional[str] = None
    func: Optional[Callable] = None
    inputs: List[str] = field(default_factory=list)


@dataclass
class TuModel:
    key: str
    file: str
    name: str
    params: List[TuParam]
    covs: Dict[str, TuCov]
    err_type: str
    sigmas: List[float]

    @property
    def eta_params(self) -> List[TuParam]:
        return [p for p in self.params if p.bsv_type != "none" and p.sd > 0]


def _txt(el, path, default=None):
    f = el.find(path)
    return f.text.strip() if f is not None and f.text else default


def parse_tdd(path: str, key: str = "") -> TuModel:
    root = ET.parse(path).getroot()
    # --- tham số ---
    params: List[TuParam] = []
    for p in root.iter("parameter"):
        pid = _txt(p, "parameterId")
        if pid is None:
            continue
        std = float(_txt(p, "parameterValue/standardValue"))
        func, inputs = None, []
        code = p.find("parameterValue/aprioriComputation/softFormula/code")
        if code is not None and code.text:
            inputs = [i.text.strip() for i in p.findall("parameterValue/aprioriComputation/softFormula/inputs/input/id")]
            func = compile_js(code.text, inputs)
        bt = _txt(p, "bsv/bsvType", "none")
        bt = {"lognormal": "exponential", "exponential": "exponential", "proportional": "proportional"}.get(bt, "none")
        sd_txt = _txt(p, "bsv/stdDevs/stdDev")
        params.append(TuParam(pid, std, inputs, func, bt, float(sd_txt) if sd_txt else 0.0))
    # --- hiệp biến ---
    covs: Dict[str, TuCov] = {}
    for c in root.iter("covariate"):
        cid = _txt(c, "covariateId")
        if cid is None:
            continue
        rp = c.find("refreshPeriod")
        refresh = None
        if rp is not None:
            u, v = _txt(rp, "unit"), float(_txt(rp, "value", "0"))
            refresh = {"d": v, "h": v / 24.0, "w": v * 7.0, "y": v * 365.0}.get(u)
        cov = TuCov(cid, _txt(c, "covariateType", "standard"), float(_txt(c, "covariateValue/standardValue", "0") if _txt(c, "covariateValue/standardValue") not in ("true", "false") else (1.0 if _txt(c, "covariateValue/standardValue") == "true" else 0.0)),
                    _txt(c, "interpolationType", "linear"), refresh)
        hf = c.find("covariateValue/aprioriComputation/hardFormula")
        if hf is not None and hf.text:
            cov.hard = hf.text.strip()
        sc = c.find("covariateValue/aprioriComputation/softFormula/code")
        if sc is not None and sc.text:
            cov.inputs = [i.text.strip() for i in c.findall("covariateValue/aprioriComputation/softFormula/inputs/input/id")]
            cov.func = compile_js(sc.text, cov.inputs)
        covs[cid] = cov
    # --- sai số còn lại ---
    em = root.find(".//errorModel")
    err_type = _txt(em, "errorModelType", "proportional")
    sig = [float(s.text) for s in em.findall("sigmas/sigma/standardValue")]
    name = os.path.basename(path)
    return TuModel(key, name, name, params, covs, err_type, sig)


_CACHE: Dict[Tuple[str, str], TuModel] = {}


def load_model(key: str, drug_dir: Optional[str] = None) -> TuModel:
    fn = MODEL_FILES[key]
    if drug_dir is None:                       # tìm .tdd: thư mục gốc app (nơi run_app tải về) -> tucuxi_models/
        here = os.path.dirname(os.path.abspath(__file__))
        drug_dir = next((d for d in (here, DEFAULT_DRUG_DIR) if os.path.exists(os.path.join(d, fn))), here)
    k = (key, drug_dir)
    if k not in _CACHE:
        _CACHE[k] = parse_tdd(os.path.join(drug_dir, fn), key)
    return _CACHE[k]


# ---------------------------------------------------------------------------------------------
# 3. Bệnh nhân, hiệp biến theo thời gian
# ---------------------------------------------------------------------------------------------
@dataclass
class TuPatient:
    age_years: float
    male: bool
    weight_kg: float
    hemodialysis: bool = False      # Goti 2018
    haem_malignancy: bool = False   # Colin 2019 (dis_haem)
    gram_positive: bool = True      # Yamamoto 2009 (dis_gpos) — mặc định của .tdd là 1
    gestational_age_w: float = 40.0  # Colin 2019: người lớn = 40 tuần


def _years_between(t: datetime.datetime, b: datetime.datetime) -> int:
    y = t.year - b.year
    if (t.month, t.day, t.hour, t.minute, t.second) < (b.month, b.day, b.hour, b.minute, b.second):
        y -= 1
    return y


def _interp(series: List[Tuple[datetime.datetime, float]], t: datetime.datetime) -> float:
    if len(series) == 1 or t <= series[0][0]:
        return series[0][1]
    if t >= series[-1][0]:
        return series[-1][1]
    for (t1, v1), (t2, v2) in zip(series, series[1:]):
        if t1 <= t <= t2:
            if t2 == t1:
                return v2
            return v1 + (v2 - v1) * (t - t1).total_seconds() / (t2 - t1).total_seconds()
    return series[-1][1]


def cockcroft_gault_general(weight, age_int, creat_umol, male) -> Optional[float]:
    """eGFR_CockcroftGaultGeneral của Tucuxi: (140−tuổi)·cân nặng / creatinine[µmol/L] × (1,23 nam | 1,04 nữ)."""
    if creat_umol <= 0 or weight <= 0 or age_int < 0:
        return None
    return (140 - age_int) * weight / creat_umol * (1.23 if male else 1.04)


def covariates_at(model: TuModel, pat: TuPatient, birth: datetime.datetime,
                  scr_series: List[Tuple[datetime.datetime, float]], t: datetime.datetime) -> Dict[str, float]:
    """Giá trị hiệp biến tại 1 mốc lưới (đúng thứ tự: chuẩn/tuổi → tính toán)."""
    v: Dict[str, float] = {}
    creat_now = _interp(scr_series, t) if scr_series else None
    age_now = _years_between(t, birth)
    patient_std = {
        "bodyweight": pat.weight_kg, "sex": 1.0 if pat.male else 0.0,
        "gestationalage": pat.gestational_age_w, "hemodialysis": 1.0 if pat.hemodialysis else 0.0,
        "dis_haem": 1.0 if pat.haem_malignancy else 0.0, "dis_gpos": 1.0 if pat.gram_positive else 0.0,
    }
    for cid, c in model.covs.items():
        if c.ctype == "ageInYears":
            v[cid] = float(_years_between(t, birth))
        elif c.ctype == "ageInDays":
            v[cid] = float((t - birth).days)
        elif c.ctype == "ageInWeeks":
            v[cid] = float((t - birth).days // 7)
        elif cid == "creatinine":
            v[cid] = _interp(scr_series, t) if scr_series else c.default
        elif cid in patient_std:
            v[cid] = patient_std[cid]
        elif c.hard is None and c.func is None:
            v[cid] = c.default
    # tính toán
    for cid, c in model.covs.items():
        if c.hard == "eGFR_CockcroftGaultGeneral":
            r = cockcroft_gault_general(pat.weight_kg, age_now, creat_now or 0.0, pat.male)
            v[cid] = r if r is not None else c.default
        elif c.func is not None:
            v[cid] = float(c.func(**{k: v[k] for k in c.inputs}))
    # clcr kiểu "standard" không có công thức (Yamamoto): người dùng Tucuxi phải NHẬP clcr — phần mềm cấp CG tại từng mốc đo
    # SCr (tuổi tại mốc đó), rồi Tucuxi nội suy tuyến tính theo thời gian như mọi hiệp biến khác.
    if "clcr" in model.covs and model.covs["clcr"].hard is None and model.covs["clcr"].func is None and scr_series:
        ser = []
        for ts, u in scr_series:
            r = cockcroft_gault_general(pat.weight_kg, _years_between(ts, birth), u, pat.male)
            if r is not None:
                ser.append((ts, r))
        if ser:
            v["clcr"] = _interp(ser, t)
    return v


def param_set(model: TuModel, cov: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for p in model.params:
        out[p.id] = float(p.func(**{k: cov[k] for k in p.inputs})) if p.func else p.std
    return out


def apply_etas(model: TuModel, tv: Dict[str, float], etas: np.ndarray) -> Dict[str, float]:
    out = dict(tv)
    for e, p in zip(etas, model.eta_params):
        e = float(e)
        if p.bsv_type == "exponential":
            out[p.id] = tv[p.id] * math.exp(max(min(e, 20.0), -20.0))
        else:
            out[p.id] = tv[p.id] * max(1.0 + e, 1e-4)      # tham số luôn dương
    return out


# ---------------------------------------------------------------------------------------------
# 4. Mô phỏng 2 ngăn (nghiệm đóng, tham số đổi theo từng liều)
# ---------------------------------------------------------------------------------------------
def _zoh(a1: float, a2: float, cl: float, v1: float, v2: float, q: float, rate: float, dt: float):
    k10, k12, k21 = cl / v1, q / v1, q / v2
    m11, m12, m21, m22 = -(k10 + k12), k21, k12, -k21
    tr, det = m11 + m22, m11 * m22 - m12 * m21
    disc = math.sqrt(max(tr * tr - 4 * det, 0.0))
    l1, l2 = (tr + disc) / 2.0, (tr - disc) / 2.0
    if abs(l1 - l2) < 1e-12:
        l2 = l1 - 1e-9
    e1, e2 = math.exp(max(l1 * dt, -700.0)), math.exp(max(l2 * dt, -700.0))
    d = l1 - l2

    def expm_apply(x1, x2):
        # e^{Mt} x = [e1 (M−l2 I) − e2 (M−l1 I)] x / (l1−l2)
        y1 = (e1 * ((m11 - l2) * x1 + m12 * x2) - e2 * ((m11 - l1) * x1 + m12 * x2)) / d
        y2 = (e1 * (m21 * x1 + (m22 - l2) * x2) - e2 * (m21 * x1 + (m22 - l1) * x2)) / d
        return y1, y2

    y1, y2 = expm_apply(a1, a2)
    if rate:
        # M^{-1}(e^{Mt} − I) b,  b = (rate, 0)
        z1, z2 = expm_apply(rate, 0.0)
        z1 -= rate
        # M^{-1} = 1/det · [[m22, −m12], [−m21, m11]]
        y1 += (m22 * z1 - m12 * z2) / det
        y2 += (-m21 * z1 + m11 * z2) / det
    return y1, y2


@dataclass
class Intake:
    t: datetime.datetime
    dose_mg: float
    tinf_h: float

    @property
    def given_at(self) -> datetime.datetime:      # tương thích VancoDose của Tab 4
        return self.t


def simulate_central(intakes: List[Intake], psets: List[Dict[str, float]], t0: datetime.datetime,
                     times: List[datetime.datetime]) -> List[float]:
    """Nồng độ ngăn trung tâm tại các mốc `times`. psets[i] = bộ tham số hiệu lực từ intakes[i].t."""
    if not intakes:
        return [0.0] * len(times)
    H = lambda t: (t - t0).total_seconds() / 3600.0
    ev = []
    for i, it in enumerate(intakes):
        ev.append((H(it.t), 0, i))                                   # đổi tham số + bắt đầu truyền
        ev.append((H(it.t) + it.tinf_h, 1, i))                       # hết truyền
    q_times = sorted(((H(t), k) for k, t in enumerate(times)))
    # Danh sách mốc cắt
    bps = sorted(set([e[0] for e in ev] + [qt for qt, _ in q_times]))
    res = [0.0] * len(times)
    rate = 0.0
    a1 = a2 = 0.0
    cur: Optional[Dict[str, float]] = None
    ev_sorted = sorted(ev)
    ei = 0
    qi = 0
    first = H(intakes[0].t)
    for bi, tb in enumerate(bps):
        # trạng thái tại tb (trước khi áp sự kiện tại tb): đã được lan truyền tới tb
        while qi < len(q_times) and q_times[qi][0] <= tb + 1e-12:
            if q_times[qi][0] >= first - 1e-12 and cur is not None:
                res[q_times[qi][1]] = a1 / cur["V1"]
            qi += 1
        while ei < len(ev_sorted) and ev_sorted[ei][0] <= tb + 1e-12:
            _, kind, i = ev_sorted[ei]
            if kind == 0:
                rate += intakes[i].dose_mg / intakes[i].tinf_h
                cur = psets[i]
            else:
                rate -= intakes[i].dose_mg / intakes[i].tinf_h
            ei += 1
        if bi + 1 < len(bps) and cur is not None:
            dt = bps[bi + 1] - tb
            if dt > 1e-12:
                a1, a2 = _zoh(a1, a2, cur["CL"], cur["V1"], cur["V2"], cur["Q"], max(rate, 0.0), dt)
    while qi < len(q_times):                                          # mốc sau điểm cắt cuối (không xảy ra)
        qi += 1
    return res


# ---------------------------------------------------------------------------------------------
# 5. Bộ ước lượng
# ---------------------------------------------------------------------------------------------
@dataclass
class TuFit:
    success: bool
    message: str
    model: TuModel
    patient: TuPatient
    etas: np.ndarray
    nll: float
    intakes: List[Intake]
    scr_series: List[Tuple[datetime.datetime, float]]
    samples: List[Tuple[datetime.datetime, float]]
    t0: datetime.datetime
    birth: datetime.datetime
    c_post: List[float]
    c_prior: List[float]
    # --- trường tương thích Tab 4 (giống VancoBayesResult) ---
    CL_optimized: float = 0.0
    Vc_optimized: float = 0.0
    Vp_optimized: float = 0.0
    Q_value: float = 0.0
    C_pred_final: float = 0.0
    OFV_final: float = 0.0
    k10: float = 0.0
    k12: float = 0.0
    k21: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0
    CL_prior: float = 0.0
    Vc_prior: float = 0.0
    Vp_prior: float = 0.0
    points: List[dict] = field(default_factory=list)
    anchor_dose: Optional[object] = None
    t_ref: Optional[datetime.datetime] = None
    cl_segments: List[Tuple[datetime.datetime, float]] = field(default_factory=list)

    # ---- dự đoán lại với liều bổ sung -------------------------------------------------
    def _psets_for(self, intakes: List[Intake], etas: np.ndarray) -> List[Dict[str, float]]:
        cache: Dict[datetime.datetime, Dict[str, float]] = {}
        out = []
        for it in intakes:
            g = grid_floor(self.t0, it.t)
            if g not in cache:
                cov = covariates_at(self.model, self.patient, self.birth, self.scr_series, g)
                cache[g] = apply_etas(self.model, param_set(self.model, cov), etas)
            out.append(cache[g])
        return out

    def params_at_cycle(self, t: datetime.datetime) -> Dict[str, float]:
        """Tham số hậu nghiệm (CL, V1, V2, Q) của chu kỳ liều đang hiệu lực tại thời điểm t — đúng cách
        cột 'CL tại thời điểm TDM N' của Tucuxi: bộ tham số gắn với liều gần nhất trước t."""
        its = [i for i in self.intakes if i.t <= t] or self.intakes[:1]
        return self._psets_for([max(its, key=lambda i: i.t)], self.etas)[0]

    def predict(self, times: List[datetime.datetime], extra_doses: Optional[List[Intake]] = None,
                kind: str = "post") -> List[float]:
        intakes = sorted(self.intakes + (extra_doses or []), key=lambda i: i.t)
        etas = self.etas if kind == "post" else np.zeros_like(self.etas)
        return simulate_central(intakes, self._psets_for(intakes, etas), self.t0, times)


def population_params(model_key: str, patient: TuPatient, scr_umol: List[Tuple[datetime.datetime, float]],
                      t_ref: datetime.datetime, drug_dir: Optional[str] = None) -> Tuple[Dict[str, float], Dict[str, float], TuModel]:
    """Tham số tiền nghiệm (η = 0) và hiệp biến tại mốc t_ref (SCr nội suy, ngoài khoảng: giữ giá trị gần nhất)."""
    model = load_model(model_key, drug_dir)
    scr = sorted(scr_umol, key=lambda x: x[0])
    birth = datetime.datetime(t_ref.year - int(round(patient.age_years)), 1, 1)
    cov = covariates_at(model, patient, birth, scr, t_ref)
    return param_set(model, cov), cov, model


def grid_floor(t0: datetime.datetime, t: datetime.datetime) -> datetime.datetime:
    n = math.floor((t - t0).total_seconds() / 86400.0)
    return t0 + TD(days=max(n, 0))


def _residual_sigma(model: TuModel, f: float) -> float:
    s = model.sigmas
    if model.err_type == "mixed":
        return math.sqrt((s[1] * f) ** 2 + s[0] ** 2)
    if model.err_type in ("proportional", "propexp", "exponential"):
        return s[0] * f
    return s[0]


def tucuxi_fit(model_key: str, patient: TuPatient, doses: List[Tuple[datetime.datetime, float, float]],
               scr_umol: List[Tuple[datetime.datetime, float]], samples: List[Tuple[datetime.datetime, float]],
               drug_dir: Optional[str] = None, anchor_time: Optional[datetime.datetime] = None) -> TuFit:
    """doses: [(thời điểm, mg, thời gian truyền h)]; scr_umol: [(thời điểm, µmol/L)]; samples: [(thời điểm, mg/L)]."""
    model = load_model(model_key, drug_dir)
    intakes = sorted((Intake(t, mg, tinf) for t, mg, tinf in doses), key=lambda i: i.t)
    scr = sorted(scr_umol, key=lambda x: x[0])
    samples = sorted(samples, key=lambda x: x[0])
    if not intakes:
        raise ValueError("Cần ít nhất 1 liều")
    ev_times = [s[0] for s in samples] or [intakes[0].t]
    first_event = anchor_time or min(ev_times)
    t0 = first_event - TD(hours=SECURE_START_H)
    ref = samples[0][0] if samples else intakes[0].t
    birth = datetime.datetime(ref.year - int(round(patient.age_years)), 1, 1)

    fit = TuFit(True, "", model, patient, np.zeros(len(model.eta_params)), 0.0, intakes, scr, samples, t0, birth, [], [])
    tv_psets = fit._psets_for(intakes, np.zeros(len(model.eta_params)))
    sd = np.array([p.sd for p in model.eta_params])
    stimes = [s[0] for s in samples]
    yobs = np.array([s[1] for s in samples])
    om_add = 0.5 * (len(sd) * math.log(2 * math.pi) + sum(math.log(x * x) for x in sd))

    # Bộ tham số của từng liều phụ thuộc lưới ngày (không phụ thuộc η): tính TV một lần, áp η nhanh
    def psets_eta(etas):
        return [apply_etas(model, tvp, etas) for tvp in tv_psets]

    def J(etas):
        f = simulate_central(intakes, psets_eta(etas), t0, stimes)
        j = om_add + 0.5 * float(np.sum((etas / sd) ** 2))
        for fi, yi in zip(f, yobs):
            sig = _residual_sigma(model, fi)
            if sig <= 0:
                return 1e12
            j += 0.5 * math.log(2 * math.pi) + math.log(sig) + 0.5 * ((yi - fi) / sig) ** 2
        return j

    etas = np.zeros(len(sd))
    if samples:
        r = minimize(J, etas, method="BFGS", options={"gtol": 1e-8, "maxiter": 400})
        r2 = minimize(J, r.x, method="Nelder-Mead", options={"xatol": 1e-7, "fatol": 1e-10, "maxiter": 2000})
        best = r2 if r2.fun <= r.fun else r
        etas, nll = best.x, float(best.fun)
        fit.message = "Tối ưu Bayes MAP (Tucuxi) hội tụ"
    else:
        nll = J(etas)
        fit.message = "Không có nồng độ đo — chỉ tiền nghiệm (η = 0)"
    fit.etas, fit.nll = etas, nll
    fit.c_post = simulate_central(intakes, psets_eta(etas), t0, stimes)
    fit.c_prior = simulate_central(intakes, tv_psets, t0, stimes)

    # Thông số cuối + đoạn CL bậc thang. Bộ tham số "hiện tại" tính tại mốc muộn nhất (liều/SCr/mẫu cuối),
    # để AUC và dự đoán liều mới dùng đúng SCr mới nhất (kể cả SCr đo SAU liều cuối).
    ps_final = psets_eta(etas)
    t_ref = max([intakes[-1].t] + [x[0] for x in scr] + [x[0] for x in samples])
    cov_now = covariates_at(model, patient, birth, scr, t_ref)
    tv_now = param_set(model, cov_now)
    last = apply_etas(model, tv_now, etas)
    tvl = tv_now
    fit.t_ref = t_ref
    fit.CL_optimized, fit.Vc_optimized, fit.Vp_optimized, fit.Q_value = last["CL"], last["V1"], last["V2"], last["Q"]
    fit.CL_prior, fit.Vc_prior, fit.Vp_prior = tvl["CL"], tvl["V1"], tvl["V2"]
    fit.k10, fit.k12, fit.k21 = last["CL"] / last["V1"], last["Q"] / last["V1"], last["Q"] / last["V2"]
    tr, det = -(fit.k10 + fit.k12 + fit.k21), fit.k10 * fit.k21
    disc = math.sqrt(max(tr * tr - 4 * det, 0.0))
    fit.alpha, fit.beta = abs((tr - disc) / 2.0), abs((tr + disc) / 2.0)   # α > β
    fit.OFV_final = 2.0 * nll
    fit.C_pred_final = fit.c_post[-1] if fit.c_post else 0.0
    fit.points = [{"t_obs": t, "c_obs": y, "c_pred": cp, "c_prior": cpr}
                  for (t, y), cp, cpr in zip(samples, fit.c_post, fit.c_prior)]
    segs: List[Tuple[datetime.datetime, float]] = []
    for it, ps in zip(intakes, ps_final):
        if not segs or abs(segs[-1][1] - ps["CL"]) > 1e-12:
            segs.append((it.t, ps["CL"]))
    fit.cl_segments = segs
    # liều "neo" = liều kề trước mẫu đo cuối (để tính AUC hiện tại như Tab 4)
    if samples:
        prev = [i for i in intakes if i.t <= samples[-1][0]]
        fit.anchor_dose = prev[-1] if prev else None
    return fit

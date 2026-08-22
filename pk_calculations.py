"""
pk_calculations.py — Các hàm tính toán Dược động học (PK) cho TDM Aminoglycosid
"""

import numpy as np
from dataclasses import dataclass
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
    is_first_dose: bool
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

def compute_dosing_weight(patient: PatientInfo, ibw: float) -> float:
    bmi = compute_bmi(patient)
    if bmi > 30.0:
        return ibw + 0.4 * (patient.weight_kg - ibw)
    else:
        return patient.weight_kg

def compute_crcl(patient: PatientInfo, bmi: float, ibw: float, dosing_weight: float) -> float:
    weight_for_cg = dosing_weight if bmi > 30.0 else patient.weight_kg
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

def compute_vd_individual_exact(dose_mg: float, ke: float, peak: float, t_inf: float, tau: float, is_first_dose: bool) -> float:
    num = dose_mg * (1 - np.exp(-ke * t_inf))
    if is_first_dose:
        den = t_inf * ke * peak
    else:
        den = t_inf * ke * peak * (1 - np.exp(-ke * tau))
    return num / den if den > 0 else 0.0

def compute_vd_individual(dose_mg: float, ke: float, peak: float, t_inf: float, tau: float, is_first_dose: bool) -> float:
    return compute_vd_individual_exact(dose_mg, ke, peak, t_inf, tau, is_first_dose)

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

def simulate_dosing_curve(ke, vd, t_inf_old, tau_old, peak_1, trough_1, dose_new, tau_new, t_inf_new, num_cycles=10):
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
                c_t = (c_max / t_inf_curr) * t_rel if t_inf_curr > 0 else c_max
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

def simulate_dosing_curve_custom(ke, vd, t_inf_old, tau_old, peak_1, trough_1, dose_new, tau_new, t_inf_new, num_cycles=10):
    return simulate_dosing_curve(ke, vd, t_inf_old, tau_old, peak_1, trough_1, dose_new, tau_new, t_inf_new, num_cycles)

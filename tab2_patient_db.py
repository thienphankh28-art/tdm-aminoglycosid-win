"""
tab2_patient_db.py — Tab "CSDL Bệnh nhân (Cloud)": tra cứu theo MSYT, hiển thị TOÀN BỘ lịch sử
TDM (Aminoglycosid — Sawchuk-Zaske & Bayesian Aréchiga-Alvarado 2020; Vancomycin — Bayesian
Goti 2018 & Collin 2019) trong MỘT bảng duy nhất, xóa theo lựa chọn (tick từng dòng, giống hệt
thao tác xóa ở Tab 4 Vancomycin), xuất báo cáo Excel, xóa toàn bộ bệnh nhân.

LƯU Ý VỀ PHẠM VI: chỉ file này được viết lại. Không đụng đến logic tính toán/lưu dữ liệu của
Tab 1, Tab 4 hay các hàm trong database.py — tab2 chỉ ĐỌC (và xóa theo bản ghi có sẵn) dữ liệu
đã có trên Cloud.

Giới hạn đã biết (không thể khắc phục nếu không sửa database.py/tab khác — ngoài phạm vi lần
này): bảng vanco_results_history hiện KHÔNG lưu "liều/τ đang dùng" riêng (chỉ có AUC), nên cột
"Liều TDM (mg)"/"Tau (h)" của các dòng Vancomycin sẽ hiển thị "—". Nút "Xóa toàn bộ bệnh nhân"
hiện chỉ xóa bảng patients/tdm_history (hành vi cũ, giữ nguyên) — muốn xóa gọn cả Vancomycin/
Aminoglycosid-Bayesian của bệnh nhân đó, dùng tick chọn từng dòng trong bảng lịch sử bên dưới.
"""

from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk
import pandas as pd

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import database as db
from ui_common import FONT_H2, FONT_SMALL, LabeledEntry, StatusLabel


def _fmt(value, digits=2):
    """Định dạng số cho bảng hợp nhất — trả về '—' nếu rỗng/None/NaN."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "—"
        return f"{float(value):.{digits}f}"
    except Exception:
        return "—"


UNIFIED_COLS = ["Chọn", "Thuốc", "Phương pháp", "Mô hình", "Ngày TDM", "Liều TDM (mg)", "Tau (h)",
                "CL", "Vc", "Vp", "AUC", "Vd", "Ke"]
UNIFIED_SOURCE_LABELS = {
    "sz": "Aminoglycosid — Sawchuk-Zaske",
    "amg_bayes": "Aminoglycosid — Bayesian",
    "vanco": "Vancomycin — Bayesian",
}


class Tab2DatabaseFrame(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.current_msyt = None
        self._unified_row_meta = {}

        outer = ctk.CTkScrollableFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True)

        ctk.CTkLabel(outer, text="Tra cứu, Quản lý & Xuất CSDL Bệnh nhân trên Cloud",
                     font=FONT_H2).pack(anchor="w", padx=6, pady=(6, 8))

        # --- Thanh công cụ Tra cứu & Xuất báo cáo ---
        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.pack(fill="x", padx=6)

        self.lookup_entry = LabeledEntry(row, "Nhập MSYT để tra cứu toàn bộ lịch sử TDM (mọi thuốc/phương pháp)")
        self.lookup_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(row, text="Tra cứu", width=120, command=self.lookup).pack(side="left", pady=(18, 4))

        ctk.CTkButton(row, text="📥 Xuất báo cáo (Excel)", width=160,
                      fg_color="#2f6f4f", hover_color="#254f39",
                      command=self.export_report).pack(side="left", padx=(10, 0), pady=(18, 4))

        self.lookup_status = StatusLabel(outer)
        self.lookup_status.pack(fill="x", padx=6, pady=(6, 0))

        # --- Thông tin hành chính bệnh nhân (tóm tắt gọn, không tách bảng riêng) ---
        self.patient_summary_label = ctk.CTkLabel(
            outer, text="Nhập MSYT và bấm Tra cứu để xem thông tin bệnh nhân.",
            font=FONT_SMALL, text_color=("gray30", "gray80"), anchor="w", justify="left")
        self.patient_summary_label.pack(anchor="w", padx=6, pady=(14, 10), fill="x")

        # --- Bảng hợp nhất TOÀN BỘ lịch sử TDM (mọi thuốc/phương pháp/mô hình) ---
        ctk.CTkLabel(outer, text="📋 Lịch sử TDM (tất cả thuốc & phương pháp)", font=FONT_H2
                     ).pack(anchor="w", padx=6, pady=(4, 4))
        ctk.CTkLabel(outer, text="Tick vào cột \"Chọn\" của (các) dòng cần xóa, rồi bấm \"🗑️ Xóa các dòng đã chọn\".",
                     font=FONT_SMALL, text_color=("gray45", "gray65")).pack(anchor="w", padx=6, pady=(0, 6))

        tree_frame = ctk.CTkFrame(outer, fg_color="transparent")
        tree_frame.pack(fill="x", padx=6, pady=(0, 6))
        self.unified_tree = ttk.Treeview(tree_frame, show="headings", height=10)
        self.unified_tree["columns"] = UNIFIED_COLS
        for col in UNIFIED_COLS:
            self.unified_tree.heading(col, text=col)
            width = 50 if col == "Chọn" else max(95, len(col) * 10)
            self.unified_tree.column(col, width=width, anchor="center")
        self.unified_tree.bind("<Button-1>", self._on_unified_tree_click)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.unified_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.unified_tree.xview)
        self.unified_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.unified_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_columnconfigure(0, weight=1)

        del_row = ctk.CTkFrame(outer, fg_color="transparent")
        del_row.pack(fill="x", padx=6, pady=(0, 4))
        ctk.CTkButton(del_row, text="🗑️ Xóa các dòng đã chọn", fg_color="#d1242f", hover_color="#a01c24",
                      command=self.delete_selected_rows).pack(side="left")
        self.delete_status = StatusLabel(outer)
        self.delete_status.pack(fill="x", padx=6, pady=(4, 4))

        # --- Vùng nguy hiểm: xóa toàn bộ bệnh nhân (giữ nguyên hành vi cũ) ---
        delete_box = ctk.CTkFrame(outer, corner_radius=10, fg_color=("gray95", "gray14"))
        delete_box.pack(fill="x", padx=6, pady=(10, 4))
        ctk.CTkLabel(delete_box,
                     text="⚠️ Xóa TOÀN BỘ hồ sơ hành chính + lịch sử TDM Aminoglycosid (Sawchuk-Zaske) "
                          "của bệnh nhân này trên Cloud! Muốn xóa gọn Vancomycin/Bayesian, hãy tick chọn "
                          "từng dòng ở bảng phía trên.",
                     font=FONT_SMALL, text_color="#9a6700", wraplength=900, justify="left"
                     ).pack(anchor="w", padx=14, pady=(12, 6))
        ctk.CTkButton(delete_box, text="Xóa toàn bộ Bệnh nhân này", fg_color="#d1242f", hover_color="#a01c24",
                      command=self.delete_patient).pack(anchor="w", padx=14, pady=(0, 14))

        ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=6, pady=16)

        # --- Biểu đồ xu hướng (Aminoglycosid — Sawchuk-Zaske) ---
        ctk.CTkLabel(outer, text="📈 Biểu đồ xu hướng TDM Aminoglycosid (Sawchuk-Zaske)", font=FONT_H2).pack(
            anchor="w", padx=6, pady=(0, 8))
        self.trend_container = ctk.CTkFrame(outer, fg_color="transparent")
        self.trend_container.pack(fill="both", expand=True, padx=6)
        self.trend_placeholder = ctk.CTkLabel(
            self.trend_container,
            text="Vui lòng nhập MSYT ở ô tra cứu phía trên để xem biểu đồ xu hướng.",
            font=FONT_SMALL, text_color=("gray40", "gray70"))
        self.trend_placeholder.pack(padx=20, pady=40)
        self.trend_canvas_drug = None
        self.trend_canvas_dose = None

    # ---------------------------------------------------------------
    # Chuẩn bị dữ liệu (DÙNG CHUNG cho hiển thị bảng hợp nhất VÀ xuất Excel)
    # ---------------------------------------------------------------
    def _prepare_vanco_dataframe(self, msyt):
        """Hàm phụ trợ lấy và gộp thông tin Bệnh nhân & Kết quả Vancomycin (dùng khi xuất Excel)."""
        df_vanco_history = db.get_vanco_results_history(msyt)
        vanco_patient = db.get_vanco_patient_current(msyt)

        if not df_vanco_history.empty:
            if vanco_patient:
                df_vanco_history["Tuổi"] = vanco_patient.get("age", "")
                df_vanco_history["Giới tính"] = vanco_patient.get("gender", "")
                df_vanco_history["Chiều cao"] = vanco_patient.get("height", "")
                df_vanco_history["Cân nặng"] = vanco_patient.get("weight", "")
                df_vanco_history["SCr"] = vanco_patient.get("scr", "")
                is_dialysis = vanco_patient.get("is_dialysis", 0)
                df_vanco_history["Lọc máu"] = "Có" if is_dialysis else "Không"
            else:
                for col in ["Tuổi", "Giới tính", "Chiều cao", "Cân nặng", "SCr", "Lọc máu"]:
                    df_vanco_history[col] = ""

            cols_to_extract = ["tdm_date", "method", "Tuổi", "Giới tính", "Chiều cao", "Cân nặng", "SCr", "Lọc máu",
                               "q_prior", "cl_prior", "vc_prior", "vp_prior",
                               "cl_optimized", "vc_optimized", "vp_optimized", "auc_current"]

            cols_present = [col for col in cols_to_extract if col in df_vanco_history.columns]
            df_vanco_filtered = df_vanco_history[cols_present]

            rename_dict = {
                "tdm_date": "Ngày TDM", "method": "Phương pháp",
                "q_prior": "Q_prior", "cl_prior": "Cl_prior", "vc_prior": "Vc_prior", "vp_prior": "Vp_prior",
                "cl_optimized": "Cl_optimized", "vc_optimized": "Vc_optimized", "vp_optimized": "Vp_optimized",
                "auc_current": "AUC_current"
            }
            df_vanco_filtered = df_vanco_filtered.rename(columns=rename_dict)
            return df_vanco_filtered
        return pd.DataFrame()

    def _prepare_amg_bayes_dataframe(self, msyt):
        """Hàm phụ trợ lấy và gộp thông tin Bệnh nhân & Kết quả TDM Aminoglycosid — phương
        pháp Bayesian (Tab 1, mô hình Aréchiga-Alvarado 2020), dùng khi xuất Excel."""
        df_amg_bayes = pd.DataFrame(db.get_amg_bayesian_results_history(msyt))
        amg_bayes_patient = db.get_amg_bayesian_patient_current(msyt)

        if not df_amg_bayes.empty:
            if amg_bayes_patient:
                df_amg_bayes["Tuổi"] = amg_bayes_patient.get("age", "")
                df_amg_bayes["Giới tính"] = amg_bayes_patient.get("gender", "")
                df_amg_bayes["Chiều cao"] = amg_bayes_patient.get("height", "")
                df_amg_bayes["Cân nặng"] = amg_bayes_patient.get("weight", "")
                df_amg_bayes["SCr"] = amg_bayes_patient.get("scr", "")
            else:
                for col in ["Tuổi", "Giới tính", "Chiều cao", "Cân nặng", "SCr"]:
                    df_amg_bayes[col] = ""

            cols_to_extract = ["tdm_date", "model", "Tuổi", "Giới tính", "Chiều cao", "Cân nặng", "SCr",
                               "cl_prior", "vd_prior", "cl_optimized", "vd_optimized", "ke",
                               "cpeak_current", "ctrough_current", "dose_used", "tau_used", "ofv_final"]

            cols_present = [col for col in cols_to_extract if col in df_amg_bayes.columns]
            df_amg_bayes_filtered = df_amg_bayes[cols_present]

            rename_dict = {
                "tdm_date": "Ngày TDM", "model": "Mô hình",
                "cl_prior": "CL_prior", "vd_prior": "Vd_prior",
                "cl_optimized": "CL_post", "vd_optimized": "Vd_post", "ke": "Ke",
                "cpeak_current": "Cpeak_current", "ctrough_current": "Ctrough_current",
                "dose_used": "Liều đang dùng", "tau_used": "τ đang dùng", "ofv_final": "OFV_final",
            }
            df_amg_bayes_filtered = df_amg_bayes_filtered.rename(columns=rename_dict)
            return df_amg_bayes_filtered
        return pd.DataFrame()

    def _build_patient_summary(self, msyt):
        """Lấy thông tin hành chính đại diện — ưu tiên bảng 'patients' (Sawchuk-Zaske), rồi
        đến bệnh nhân hiện tại của Vancomycin, rồi đến Aminoglycosid-Bayesian."""
        df_patient = db.get_patient_by_msyt(msyt)
        if not df_patient.empty:
            r = df_patient.iloc[0]
            return {"age": r.get("age"), "gender": r.get("gender"), "height": r.get("height"), "weight": r.get("weight")}
        vp = db.get_vanco_patient_current(msyt)
        if vp:
            return {"age": vp.get("age"), "gender": vp.get("gender"), "height": vp.get("height"), "weight": vp.get("weight")}
        ap = db.get_amg_bayesian_patient_current(msyt)
        if ap:
            return {"age": ap.get("age"), "gender": ap.get("gender"), "height": ap.get("height"), "weight": ap.get("weight")}
        return None

    def _build_unified_rows(self, msyt):
        """Gộp lịch sử TDM từ CẢ 3 nguồn (Sawchuk-Zaske, Aminoglycosid-Bayesian, Vancomycin)
        thành 1 danh sách dict đồng nhất cột, sắp xếp theo Ngày TDM mới nhất trước."""
        rows = []

        # --- Aminoglycosid — Sawchuk-Zaske (tdm_history) ---
        df_hist = db.get_history_by_msyt(msyt)
        if not df_hist.empty:
            for _, r in df_hist.iterrows():
                ke, vd = r.get("ke"), r.get("vd")
                cl = (ke * vd) if pd.notnull(ke) and pd.notnull(vd) else None
                tdm_date = str(r.get("tdm_date", ""))
                rows.append({
                    "source": "sz", "msyt": msyt, "tdm_date": tdm_date,
                    "Thuốc": "Aminoglycosid", "Phương pháp": "Sawchuk-Zaske", "Mô hình": "—",
                    "Ngày TDM": tdm_date,
                    "Liều TDM (mg)": _fmt(r.get("new_dose"), 0), "Tau (h)": _fmt(r.get("new_tau"), 0),
                    "CL": _fmt(cl, 3), "Vc": "—", "Vp": "—", "AUC": "—",
                    "Vd": _fmt(vd, 2), "Ke": _fmt(ke, 4),
                })

        # --- Aminoglycosid — Bayesian (Aréchiga-Alvarado 2020) ---
        for r in db.get_amg_bayesian_results_history(msyt):
            tdm_date = str(r.get("tdm_date", ""))
            rows.append({
                "source": "amg_bayes", "msyt": msyt, "tdm_date": tdm_date,
                "Thuốc": "Aminoglycosid", "Phương pháp": "Bayesian", "Mô hình": r.get("model") or "—",
                "Ngày TDM": tdm_date,
                "Liều TDM (mg)": _fmt(r.get("dose_used"), 0), "Tau (h)": _fmt(r.get("tau_used"), 0),
                "CL": _fmt(r.get("cl_optimized"), 3), "Vc": "—", "Vp": "—", "AUC": "—",
                "Vd": _fmt(r.get("vd_optimized"), 2), "Ke": _fmt(r.get("ke"), 4),
            })

        # --- Vancomycin — Bayesian (Goti 2018 / Collin 2019) ---
        df_vanco = db.get_vanco_results_history(msyt)
        if not df_vanco.empty:
            for _, r in df_vanco.iterrows():
                tdm_date = str(r.get("tdm_date", ""))
                rows.append({
                    "source": "vanco", "msyt": msyt, "tdm_date": tdm_date,
                    "Thuốc": "Vancomycin", "Phương pháp": "Bayesian", "Mô hình": r.get("method") or "—",
                    "Ngày TDM": tdm_date,
                    "Liều TDM (mg)": "—", "Tau (h)": "—",
                    "CL": _fmt(r.get("cl_optimized"), 3), "Vc": _fmt(r.get("vc_optimized"), 2),
                    "Vp": _fmt(r.get("vp_optimized"), 2), "AUC": _fmt(r.get("auc_current"), 2),
                    "Vd": "—", "Ke": "—",
                })

        rows.sort(key=lambda x: x["Ngày TDM"], reverse=True)
        return rows

    # ---------------------------------------------------------------
    # Bảng hợp nhất: hiển thị + chọn (tick) + xóa (y hệt thao tác ở Tab 4 Vancomycin)
    # ---------------------------------------------------------------
    def _fill_unified_tree(self, msyt):
        self.unified_tree.delete(*self.unified_tree.get_children())
        self._unified_row_meta = {}
        rows = self._build_unified_rows(msyt)
        for r in rows:
            values = ["☐"] + [r.get(c, "—") for c in UNIFIED_COLS[1:]]
            iid = self.unified_tree.insert("", "end", values=values)
            self._unified_row_meta[iid] = {"source": r["source"], "msyt": r["msyt"], "tdm_date": r["tdm_date"]}
        return len(rows)

    def _on_unified_tree_click(self, event):
        """Click vào cột 'Chọn' sẽ đảo trạng thái tick (☐ <-> ☑) của dòng đó."""
        region = self.unified_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.unified_tree.identify_column(event.x)
        row_iid = self.unified_tree.identify_row(event.y)
        if not row_iid:
            return
        if col == "#1":
            vals = list(self.unified_tree.item(row_iid, "values"))
            vals[0] = "☑" if vals[0] == "☐" else "☐"
            self.unified_tree.item(row_iid, values=vals)

    def _get_checked_unified_rows(self):
        checked = []
        for iid in self.unified_tree.get_children():
            vals = self.unified_tree.item(iid, "values")
            if vals and vals[0] == "☑":
                meta = self._unified_row_meta.get(iid)
                if meta:
                    checked.append(meta)
        return checked

    def delete_selected_rows(self):
        """Xóa (các) dòng TDM đã tick chọn — bất kể thuộc thuốc/phương pháp nào — sau khi
        người dùng xác nhận 2 lần (đúng thao tác đã dùng ở Tab 4 Vancomycin)."""
        checked = self._get_checked_unified_rows()
        if not checked:
            self.delete_status.show("⚠️ Chưa chọn dòng dữ liệu nào để xóa (tick vào cột \"Chọn\").", "warning")
            return

        lines = "\n".join(f"  • [{UNIFIED_SOURCE_LABELS.get(m['source'], m['source'])}] Ngày {m['tdm_date']}"
                          for m in checked)
        if not messagebox.askyesno(
                "Xác nhận xóa",
                f"Bạn sắp xóa {len(checked)} lần TDM của bệnh nhân {self.current_msyt}:\n{lines}\n\nTiếp tục?"):
            return
        if not messagebox.askyesno(
                "Xác nhận lần cuối",
                "⚠️ Hành động này KHÔNG THỂ HOÀN TÁC. Dữ liệu sẽ bị xóa vĩnh viễn trên Cloud.\n\n"
                "Bạn có chắc chắn muốn xóa?"):
            return

        ok_count, fail_msgs = 0, []
        for m in checked:
            if m["source"] == "sz":
                ok, msg = db.delete_tdm_block(m["msyt"], m["tdm_date"])
            elif m["source"] == "amg_bayes":
                ok, msg = db.delete_amg_bayesian_result_block(m["msyt"], m["tdm_date"])
            else:
                ok, msg = db.delete_vanco_result_block(m["msyt"], m["tdm_date"])
            if ok:
                ok_count += 1
            else:
                fail_msgs.append(f"{m['tdm_date']}: {msg}")

        if ok_count and not fail_msgs:
            self.delete_status.show(f"✅ Đã xóa thành công {ok_count} dòng dữ liệu.", "success")
        elif ok_count and fail_msgs:
            self.delete_status.show(
                f"⚠️ Đã xóa {ok_count} dòng, còn {len(fail_msgs)} dòng lỗi: " + "; ".join(fail_msgs), "warning")
        else:
            self.delete_status.show("❌ Xóa thất bại: " + "; ".join(fail_msgs), "error")

        self.lookup()

    # ---------------------------------------------------------------
    def lookup(self):
        msyt = self.lookup_entry.get().strip()
        self.current_msyt = msyt
        if not msyt:
            self.lookup_status.show("⚠️ Vui lòng nhập MSYT.", "warning")
            return

        n_rows = self._fill_unified_tree(msyt)
        demo = self._build_patient_summary(msyt)

        if demo:
            self.patient_summary_label.configure(text=(
                f"MSYT: {msyt}   |   Tuổi: {demo.get('age') if demo.get('age') is not None else '—'}"
                f"   |   Giới tính: {demo.get('gender') or '—'}"
                f"   |   Chiều cao: {demo.get('height') if demo.get('height') is not None else '—'} cm"
                f"   |   Cân nặng: {demo.get('weight') if demo.get('weight') is not None else '—'} kg"))
        else:
            self.patient_summary_label.configure(text=f"MSYT: {msyt}   |   Không có thông tin hành chính lưu trữ.")

        if n_rows > 0 or demo:
            self.lookup_status.show(f"✅ Đã tải thông tin và {n_rows} lần TDM của bệnh nhân {msyt}.", "success")
        else:
            self.lookup_status.show("❌ Không tìm thấy bệnh nhân với MSYT vừa nhập trên Cloud.", "error")

        self._refresh_trend(msyt)

    def export_report(self):
        """Xuất dữ liệu Aminoglycosid (cả 2 phương pháp) và Vancomycin của bệnh nhân ra Excel."""
        if not self.current_msyt:
            self.lookup_status.show("⚠️ Vui lòng tra cứu một bệnh nhân trước khi xuất báo cáo.", "warning")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialfile=f"Bao_Cao_TDM_{self.current_msyt}.xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            title="Lưu báo cáo TDM (Excel)"
        )
        if not filepath:
            return

        try:
            df_patient = db.get_patient_by_msyt(self.current_msyt)
            df_history = db.get_history_by_msyt(self.current_msyt)
            df_amg_bayes_final = self._prepare_amg_bayes_dataframe(self.current_msyt)
            df_vanco_final = self._prepare_vanco_dataframe(self.current_msyt)

            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                # Sheet 1: Dữ liệu Aminoglycosid (Sawchuk-Zaske)
                if not df_patient.empty or not df_history.empty:
                    if not df_patient.empty:
                        df_patient.to_excel(writer, sheet_name='Aminoglycosid', startrow=0, index=False)
                    if not df_history.empty:
                        start_row = len(df_patient) + 3 if not df_patient.empty else 0
                        worksheet = writer.sheets['Aminoglycosid']
                        worksheet.cell(row=start_row, column=1, value="LỊCH SỬ TDM AMINOGLYCOSID")
                        df_history.to_excel(writer, sheet_name='Aminoglycosid', startrow=start_row, index=False)

                # Sheet 2: Dữ liệu Aminoglycosid — Bayesian (Aréchiga-Alvarado 2020)
                if not df_amg_bayes_final.empty:
                    df_amg_bayes_final.to_excel(writer, sheet_name='AMG_Bayesian', index=False)

                # Sheet 3: Dữ liệu Vancomycin (Đã ghép chung bệnh nhân & kết quả)
                if not df_vanco_final.empty:
                    df_vanco_final.to_excel(writer, sheet_name='Vancomycin', index=False)

                if df_patient.empty and df_history.empty and df_amg_bayes_final.empty and df_vanco_final.empty:
                    empty_df = pd.DataFrame(["Bệnh nhân chưa có dữ liệu trên hệ thống."])
                    empty_df.to_excel(writer, sheet_name='No Data', index=False, header=False)

            self.lookup_status.show(f"✅ Đã xuất báo cáo Excel thành công tại: {filepath}", "success")
        except Exception as e:
            self.lookup_status.show(f"❌ Có lỗi xảy ra khi xuất báo cáo Excel: {e}", "error")

    def delete_patient(self):
        if not self.current_msyt:
            self.delete_status.show("⚠️ Không có bệnh nhân nào được chọn.", "warning")
            return
        if messagebox.askyesno("Xác nhận xóa vĩnh viễn",
                                f"⚠️ Xóa hồ sơ hành chính + lịch sử TDM Aminoglycosid (Sawchuk-Zaske) của "
                                f"bệnh nhân {self.current_msyt}?\nThao tác này không thể hoàn tác!"):
            ok, msg = db.delete_patient(self.current_msyt)
            self.delete_status.show(("✅ " if ok else "❌ ") + msg, "success" if ok else "error")
            self.lookup()

    def _refresh_trend(self, msyt):
        try:
            response = db.supabase.table("tdm_history").select("*").eq("msyt", msyt).execute()
            df = pd.DataFrame(response.data) if response.data else pd.DataFrame()
        except Exception as e:
            self.delete_status.show(f"❌ Lỗi khi tải dữ liệu biểu đồ từ Supabase: {e}", "error")
            df = pd.DataFrame()

        for child in self.trend_container.winfo_children():
            child.destroy()
        self.trend_canvas_drug = None
        self.trend_canvas_dose = None

        if df.empty:
            ctk.CTkLabel(self.trend_container, text="Không có bản ghi TDM Aminoglycosid (Sawchuk-Zaske) nào để vẽ biểu đồ.",
                         font=FONT_SMALL, text_color=("gray40", "gray70")).pack(padx=20, pady=40)
            return

        df_sorted = df.sort_values("tdm_date")
        self.trend_container.grid_columnconfigure((0, 1), weight=1)

        left = ctk.CTkFrame(self.trend_container, fg_color=("gray95", "gray14"), corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=6)
        ctk.CTkLabel(left, text=f"Nồng độ thuốc thực tế (MSYT: {msyt})", font=FONT_SMALL).pack(pady=(8, 0))
        if "true_peak" in df_sorted.columns and "true_trough" in df_sorted.columns:
            fig1 = Figure(figsize=(5, 3.6), dpi=100)
            ax1 = fig1.add_subplot(111)
            ax1.plot(df_sorted["tdm_date"], df_sorted["true_peak"], "o-", color="red", label="C đỉnh thực tế (Peak)")
            ax1.plot(df_sorted["tdm_date"], df_sorted["true_trough"], "o-", color="blue", label="C đáy thực tế (Trough)")
            ax1.set_xlabel("Ngày TDM")
            ax1.set_ylabel("Nồng độ (µg/mL)")
            ax1.legend(fontsize=7)
            ax1.tick_params(axis="x", rotation=30, labelsize=7)
            fig1.tight_layout()
            self.trend_canvas_drug = FigureCanvasTkAgg(fig1, master=left)
            self.trend_canvas_drug.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        else:
            ctk.CTkLabel(left, text="Chưa có dữ liệu nồng độ đỉnh/đáy thực tế.",
                         font=FONT_SMALL, text_color=("gray40", "gray70")).pack(padx=20, pady=40)

        right = ctk.CTkFrame(self.trend_container, fg_color=("gray95", "gray14"), corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=6)
        ctk.CTkLabel(right, text=f"Liều mới khuyến nghị (MSYT: {msyt})", font=FONT_SMALL).pack(pady=(8, 0))
        if "new_dose" in df_sorted.columns:
            fig2 = Figure(figsize=(5, 3.6), dpi=100)
            ax2 = fig2.add_subplot(111)
            ax2.plot(df_sorted["tdm_date"], df_sorted["new_dose"], "o-", color="green", label="Liều mới (mg)")
            ax2.set_xlabel("Ngày TDM")
            ax2.set_ylabel("Liều (mg)")
            ax2.legend(fontsize=7)
            ax2.tick_params(axis="x", rotation=30, labelsize=7)
            fig2.tight_layout()
            self.trend_canvas_dose = FigureCanvasTkAgg(fig2, master=right)
            self.trend_canvas_dose.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        else:
            ctk.CTkLabel(right, text="Chưa có thông tin liều mới.",
                         font=FONT_SMALL, text_color=("gray40", "gray70")).pack(padx=20, pady=40)

"""
tab2_patient_db.py — Tab "CSDL Bệnh nhân (Cloud)": tra cứu, xem lịch sử TDM, xóa bệnh nhân /
block TDM trên Supabase Cloud.

Tách riêng khỏi app.py để phát triển/bảo trì độc lập với các tab khác.
"""

from tkinter import ttk, messagebox

import customtkinter as ctk

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import database as db
from ui_common import FONT_H2, FONT_SMALL, LabeledEntry, StatusLabel


class Tab2DatabaseFrame(ctk.CTkFrame):

    def __init__(self, master, app):

        super().__init__(master, fg_color="transparent")

        self.app = app

        self.current_msyt = None

        self.history_dates = []



        outer = ctk.CTkScrollableFrame(self, fg_color="transparent")

        outer.pack(fill="both", expand=True)



        ctk.CTkLabel(outer, text="Tra cứu & Quản lý CSDL Bệnh nhân trên Cloud",

                     font=FONT_H2).pack(anchor="w", padx=6, pady=(6, 8))



        row = ctk.CTkFrame(outer, fg_color="transparent")

        row.pack(fill="x", padx=6)

        self.lookup_entry = LabeledEntry(row, "Nhập MSYT để tra cứu thông tin và quản lý lịch sử TDM")

        self.lookup_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(row, text="Tra cứu", width=120, command=self.lookup).pack(side="left", pady=(18, 4))

        self.lookup_status = StatusLabel(outer)

        self.lookup_status.pack(fill="x", padx=6, pady=(6, 0))



        ctk.CTkLabel(outer, text="Thông tin hành chính bệnh nhân", font=FONT_SMALL,

                     text_color=("gray30", "gray75")).pack(anchor="w", padx=6, pady=(14, 4))

        self.patient_tree = self._make_treeview(outer)



        ctk.CTkLabel(outer, text="Lịch sử các Block TDM", font=FONT_SMALL,

                     text_color=("gray30", "gray75")).pack(anchor="w", padx=6, pady=(14, 4))

        self.history_tree = self._make_treeview(outer, height=6)



        delete_box = ctk.CTkFrame(outer, corner_radius=10, fg_color=("gray95", "gray14"))

        delete_box.pack(fill="x", padx=6, pady=(14, 4))

        ctk.CTkLabel(delete_box, text="🗑️ Tùy chọn xóa dữ liệu trên Cloud", font=FONT_SMALL,

                     text_color=("gray20", "gray85")).pack(anchor="w", padx=14, pady=(12, 6))



        del_row = ctk.CTkFrame(delete_box, fg_color="transparent")

        del_row.pack(fill="x", padx=14)

        self.date_option_var = ctk.StringVar(value="—")

        self.date_option = ctk.CTkOptionMenu(del_row, values=["—"], variable=self.date_option_var, width=180)

        self.date_option.pack(side="left")

        ctk.CTkButton(del_row, text="Xóa Block TDM ngày này", fg_color="#b54708", hover_color="#8a3505",

                      command=self.delete_block).pack(side="left", padx=(10, 0))



        ctk.CTkLabel(delete_box,

                     text="⚠️ Thao tác dưới đây sẽ xóa vĩnh viễn thông tin và toàn bộ lịch sử TDM "

                          "của bệnh nhân này trên Cloud!",

                     font=FONT_SMALL, text_color="#9a6700", wraplength=700, justify="left"

                     ).pack(anchor="w", padx=14, pady=(12, 6))

        ctk.CTkButton(delete_box, text="Xóa toàn bộ Bệnh nhân này", fg_color="#d1242f", hover_color="#a01c24",

                      command=self.delete_patient).pack(anchor="w", padx=14, pady=(0, 14))



        self.delete_status = StatusLabel(outer)

        self.delete_status.pack(fill="x", padx=6)



        ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=6, pady=16)



        ctk.CTkLabel(outer, text="📈 Biểu đồ xu hướng TDM theo bệnh nhân", font=FONT_H2).pack(

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



    def _make_treeview(self, master, height=5):

        frame = ctk.CTkFrame(master, fg_color="transparent")

        frame.pack(fill="x", padx=6, pady=(0, 6))

        tree = ttk.Treeview(frame, show="headings", height=height)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)

        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)

        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        tree.grid(row=0, column=0, sticky="nsew")

        vsb.grid(row=0, column=1, sticky="ns")

        hsb.grid(row=1, column=0, sticky="ew")

        frame.grid_columnconfigure(0, weight=1)

        return tree



    def _fill_treeview(self, tree, df):

        tree.delete(*tree.get_children())

        tree["columns"] = list(df.columns) if not df.empty else []

        for col in tree["columns"]:

            tree.heading(col, text=col)

            tree.column(col, width=110, anchor="center")

        for _, row in df.iterrows():

            tree.insert("", "end", values=list(row.values))



    def lookup(self):

        msyt = self.lookup_entry.get().strip()

        self.current_msyt = msyt

        if not msyt:

            self.lookup_status.show("⚠️ Vui lòng nhập MSYT.", "warning")

            return



        df_patient = db.get_patient_by_msyt(msyt)

        df_history = db.get_history_by_msyt(msyt)



        if not df_patient.empty:

            self._fill_treeview(self.patient_tree, df_patient)

            self.lookup_status.show(f"✅ Đã tìm thấy bệnh nhân {msyt}.", "success")

            if not df_history.empty:

                self._fill_treeview(self.history_tree, df_history)

                self.history_dates = df_history["tdm_date"].tolist()

                self.date_option.configure(values=[str(d) for d in self.history_dates])

                self.date_option_var.set(str(self.history_dates[0]))

            else:

                self._fill_treeview(self.history_tree, db.pd.DataFrame())

                self.history_dates = []

                self.date_option.configure(values=["—"])

                self.date_option_var.set("—")

                self.lookup_status.show("ℹ️ Bệnh nhân này chưa có lịch sử TDM trên Cloud.", "info")

        else:

            self._fill_treeview(self.patient_tree, db.pd.DataFrame())

            self._fill_treeview(self.history_tree, db.pd.DataFrame())

            self.history_dates = []

            self.lookup_status.show("❌ Không tìm thấy bệnh nhân với MSYT vừa nhập trên Cloud.", "error")



        self._refresh_trend(msyt)



    def delete_block(self):

        if not self.current_msyt or self.date_option_var.get() == "—":

            self.delete_status.show("⚠️ Không có block TDM nào được chọn.", "warning")

            return

        date_sel = self.date_option_var.get()

        if messagebox.askyesno("Xác nhận xóa", f"Xóa block TDM ngày {date_sel} của bệnh nhân {self.current_msyt}?"):

            ok, msg = db.delete_tdm_block(self.current_msyt, date_sel)

            self.delete_status.show(("✅ " if ok else "❌ ") + msg, "success" if ok else "error")

            self.lookup()



    def delete_patient(self):

        if not self.current_msyt:

            self.delete_status.show("⚠️ Không có bệnh nhân nào được chọn.", "warning")

            return

        if messagebox.askyesno("Xác nhận xóa vĩnh viễn",

                                f"⚠️ Xóa TOÀN BỘ hồ sơ và lịch sử TDM của bệnh nhân {self.current_msyt}?\n"

                                f"Thao tác này không thể hoàn tác!"):

            ok, msg = db.delete_patient(self.current_msyt)

            self.delete_status.show(("✅ " if ok else "❌ ") + msg, "success" if ok else "error")

            self.lookup()



    def _refresh_trend(self, msyt):

        try:

            response = db.supabase.table("tdm_history").select("*").eq("msyt", msyt).execute()

            df = db.pd.DataFrame(response.data) if response.data else db.pd.DataFrame()

        except Exception as e:

            self.delete_status.show(f"❌ Lỗi khi tải dữ liệu từ Supabase: {e}", "error")

            df = db.pd.DataFrame()



        for child in self.trend_container.winfo_children():

            child.destroy()

        self.trend_canvas_drug = None

        self.trend_canvas_dose = None



        if df.empty:

            ctk.CTkLabel(self.trend_container, text="Không có bản ghi TDM nào để vẽ biểu đồ cho MSYT này.",

                         font=FONT_SMALL, text_color=("gray40", "gray70")).pack(padx=20, pady=40)

            return



        df_sorted = df.sort_values("tdm_date")

        self.trend_container.grid_columnconfigure((0, 1), weight=1)



        # Biểu đồ nồng độ thực tế (Peak/Trough)

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



        # Biểu đồ liều mới khuyến nghị

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





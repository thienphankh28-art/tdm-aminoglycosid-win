"""

app.py — Điểm điều phối chính (entry point) của phần mềm TDM Aminoglycosid / Vancomycin

(CustomTkinter Desktop App).



File này CHỈ còn chứa: cấu hình giao diện chung, khung sau đăng nhập (MainAppFrame — ghép

4 tab lại với nhau) và lớp ứng dụng chính (TDMApp) + hàm main(). Toàn bộ logic của từng tab

đã được TÁCH RIÊNG ra các file độc lập để dễ phát triển/bảo trì mà không đụng chạm lẫn nhau:



    ui_common.py            — hằng số, hàm tiện ích, widget dùng chung (LabeledEntry, MetricCard...)

    login_frame.py          — màn hình đăng nhập (LoginFrame)

    tab1_aminoglycosid.py   — Tab 1: Tính toán & TDM Aminoglycosid (Tab1CalcFrame)

    tab2_patient_db.py      — Tab 2: CSDL Bệnh nhân trên Cloud (Tab2DatabaseFrame)

    tab3_info.py            — Tab 3: Thông tin phần mềm (Tab3InfoFrame)

    tab4_vancomycin.py      — Tab 4: TDM Vancomycin Bayes (Tab4VancoFrame)



Muốn sửa/thêm tính năng cho MỘT tab cụ thể, chỉ cần mở đúng file tương ứng ở trên — KHÔNG

cần đụng vào app.py hay các tab khác. database.py, pk_calculations.py, vanco_calculations.py

(lớp logic nghiệp vụ, không phải UI) vẫn giữ nguyên như trước, không bị ảnh hưởng bởi lần

tách file này.

"""



import customtkinter as ctk



import database as db

from ui_common import FONT_H1, FONT_H2, FONT_SMALL

from login_frame import LoginFrame

from tab1_aminoglycosid import Tab1CalcFrame

from tab2_patient_db import Tab2DatabaseFrame

from tab3_info import Tab3InfoFrame

from tab4_vancomycin import Tab4VancoFrame





# =============================================================================

# CẤU HÌNH GIAO DIỆN CHUNG

# =============================================================================

ctk.set_appearance_mode("light")

ctk.set_default_color_theme("blue")





class MainAppFrame(ctk.CTkFrame):



    def __init__(self, master, app, username, fullname, role):



        super().__init__(master, fg_color="transparent")



        self.app = app



        self.username, self.fullname, self.role = username, fullname, role







        self.grid_columnconfigure(1, weight=1)



        self.grid_rowconfigure(0, weight=1)







        self._build_sidebar()



        self._build_content()







    def _build_sidebar(self):



        sidebar = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=("gray90", "gray13"))



        sidebar.grid(row=0, column=0, sticky="nsw")



        sidebar.grid_propagate(False)







        ctk.CTkLabel(sidebar, text="👤 Thông tin tài khoản", font=FONT_H2).pack(anchor="w", padx=18, pady=(24, 12))



        ctk.CTkLabel(sidebar, text=f"Họ tên:\n{self.fullname}", font=FONT_SMALL, justify="left",



                     anchor="w").pack(anchor="w", padx=18, pady=4)



        ctk.CTkLabel(sidebar, text=f"Tài khoản: {self.username}", font=FONT_SMALL,



                     anchor="w").pack(anchor="w", padx=18, pady=4)



        ctk.CTkLabel(sidebar, text=f"Vai trò: {self.role}", font=FONT_SMALL,



                     anchor="w").pack(anchor="w", padx=18, pady=4)







        if self.role == "admin":



            badge = ctk.CTkLabel(sidebar, text="⚙️ Quyền Quản trị viên (Admin)", font=FONT_SMALL,



                                  fg_color="#0969da", text_color="white", corner_radius=6)



            badge.pack(anchor="w", padx=18, pady=(10, 4), ipadx=6, ipady=4)







        ctk.CTkButton(sidebar, text="🚪 Đăng xuất", fg_color="#d1242f", hover_color="#a01c24",



                      command=self.app.logout).pack(side="bottom", fill="x", padx=18, pady=24)







    def _build_content(self):



        content = ctk.CTkFrame(self, fg_color="transparent")



        content.grid(row=0, column=1, sticky="nsew", padx=18, pady=14)



        content.grid_rowconfigure(1, weight=1)



        content.grid_columnconfigure(0, weight=1)







        ctk.CTkLabel(content, text="💊 Phần mềm TDM Aminoglycosid", font=FONT_H1).grid(



            row=0, column=0, sticky="w", pady=(0, 10))







        tabview = ctk.CTkTabview(content)



        tabview.grid(row=1, column=0, sticky="nsew")



        tab1 = tabview.add("🧮 Tính toán & TDM")



        tab2 = tabview.add("🗂 CSDL Bệnh nhân (Cloud)")



        tab3 = tabview.add("ℹ️ Thông tin phần mềm")



        tab4 = tabview.add("💉 TDM Vancomycin (Bayes)")







        for tab in (tab1, tab2, tab3, tab4):



            tab.grid_columnconfigure(0, weight=1)



            tab.grid_rowconfigure(0, weight=1)







        Tab1CalcFrame(tab1, self.app).grid(row=0, column=0, sticky="nsew")



        Tab2DatabaseFrame(tab2, self.app).grid(row=0, column=0, sticky="nsew")



        Tab3InfoFrame(tab3, self.app).grid(row=0, column=0, sticky="nsew")



        Tab4VancoFrame(tab4, self.app).grid(row=0, column=0, sticky="nsew")













class TDMApp(ctk.CTk):



    def __init__(self):



        super().__init__()



        self.title("💊 Phần mềm TDM Aminoglycosid")



        self.geometry("1280x820")



        self.minsize(1024, 680)







        db.init_db()







        self.current_frame = None



        self.show_login()







    def _clear(self):



        if self.current_frame is not None:



            self.current_frame.destroy()



            self.current_frame = None







    def show_login(self):



        self._clear()



        self.current_frame = LoginFrame(self, on_success=self.show_main)



        self.current_frame.pack(fill="both", expand=True)







    def show_main(self, username, fullname, role):



        self._clear()



        self.current_frame = MainAppFrame(self, self, username, fullname, role)



        self.current_frame.pack(fill="both", expand=True)







    def logout(self):



        self.show_login()











def main():



    """Điểm khởi chạy giao diện Windows (được gọi từ run_app.py)"""



    app = TDMApp()



    app.mainloop()











if __name__ == "__main__":



    main()




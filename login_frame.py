"""
login_frame.py — Màn hình đăng nhập (LoginFrame) cho phần mềm TDM Aminoglycosid.
Tách riêng khỏi app.py để dễ chỉnh sửa/bảo trì độc lập.
"""

import customtkinter as ctk

import database as db
from ui_common import FONT_H1, FONT_H2, FONT_SMALL, LabeledEntry, StatusLabel


class LoginFrame(ctk.CTkFrame):

    def __init__(self, master, on_success):

        super().__init__(master, fg_color="transparent")

        self.on_success = on_success



        card = ctk.CTkFrame(self, corner_radius=16, width=420)

        card.place(relx=0.5, rely=0.5, anchor="center")



        ctk.CTkLabel(card, text="🔐 Đăng nhập hệ thống", font=FONT_H1).pack(padx=40, pady=(36, 4))

        ctk.CTkLabel(card, text="TDM Aminoglycosid — Vui lòng đăng nhập bằng tài khoản\nđược cấp trên hệ thống Cloud.",

                     font=FONT_SMALL, text_color=("gray40", "gray70"), justify="center").pack(padx=40, pady=(0, 20))



        self.user_entry = LabeledEntry(card, "Tên đăng nhập")

        self.user_entry.pack(fill="x", padx=40, pady=(0, 6))



        ctk.CTkLabel(card, text="Mật khẩu", anchor="w", font=FONT_SMALL,

                     text_color=("gray20", "gray85")).pack(anchor="w", padx=40)

        self.pass_var = ctk.StringVar()

        self.pass_entry = ctk.CTkEntry(card, textvariable=self.pass_var, show="•")

        self.pass_entry.pack(fill="x", padx=40, pady=(2, 10))

        self.pass_entry.bind("<Return>", lambda e: self.try_login())



        self.status = StatusLabel(card)

        self.status.pack(fill="x", padx=40, pady=(0, 6))



        ctk.CTkButton(card, text="Đăng nhập", command=self.try_login,

                      height=38, font=FONT_H2).pack(fill="x", padx=40, pady=(6, 36))



    def try_login(self):

        username = self.user_entry.get().strip()

        password = self.pass_entry.get()

        if not username or not password:

            self.status.show("⚠️ Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.", "warning")

            return

        user_data = db.check_login(username, password)

        if user_data:

            fullname, role = user_data

            self.status.show(f"✅ Đăng nhập thành công! Xin chào bác sĩ/dược sĩ {fullname}.", "success")

            self.on_success(username, fullname, role)

        else:

            self.status.show("❌ Tên đăng nhập, mật khẩu không đúng hoặc chưa kết nối được Cloud!", "error")





"""
tab3_info.py — Tab "Thông tin phần mềm & Quản trị": thông tin bản quyền, phiên bản, hướng dẫn nhanh
và (CHỈ với tài khoản có vai trò 'admin') quản trị tài khoản: cấp tài khoản mới, đặt lại mật khẩu.

Phiên bản 17/10/2026. Bảo mật: mọi thao tác quản trị đều gọi hàm SECURITY DEFINER trên Supabase
(amg_list_users / amg_add_user / amg_reset_password) — Supabase tự kiểm tra quyền admin bằng tài khoản
và mật khẩu của phiên đăng nhập; việc ẩn giao diện với người không phải admin chỉ để gọn màn hình.
Cần chạy SQL C1 (sql_C1_quan_tri_tai_khoan.sql) một lần trước khi dùng.
"""

import os
import json
import secrets
import string

import customtkinter as ctk
from tkinter import ttk, messagebox

import database as db
from ui_common import (FONT_H1, FONT_H2, FONT_NORMAL, FONT_SMALL, COPYRIGHT_EMAIL, DEFAULT_VERSION,
                       LabeledEntry, StatusLabel)

ADMIN_ROLE = "admin"
MIN_PASSWORD_LEN = 6
_PW_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "O0Il1")


def generate_password(n: int = 10) -> str:
    """Mật khẩu tạm ngẫu nhiên (bỏ các ký tự dễ nhầm O/0/I/l/1), có cả chữ hoa, chữ thường và số."""
    while True:
        pw = "".join(secrets.choice(_PW_ALPHABET) for _ in range(n))
        if any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def validate_new_password(pw: str, pw2: str):
    """Trả về chuỗi lỗi hoặc None."""
    if not pw:
        return "Chưa nhập mật khẩu."
    if len(pw) < MIN_PASSWORD_LEN:
        return f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LEN} ký tự."
    if pw != pw2:
        return "Hai lần nhập mật khẩu không khớp."
    if pw != pw.strip():
        return "Mật khẩu không được bắt đầu/kết thúc bằng khoảng trắng."
    return None


def validate_username(u: str):
    if len(u) < 3 or any(c.isspace() for c in u):
        return "Tên đăng nhập phải có ít nhất 3 ký tự và không chứa khoảng trắng."
    return None


class Tab3InfoFrame(ctk.CTkScrollableFrame):

    def __init__(self, master, app, username=None, role=None):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.username = username
        self.role = role
        self._users = []
        self._build_info()
        if str(role or "").strip().lower() == ADMIN_ROLE:
            self._build_admin()

    # -----------------------------------------------------------------
    # THÔNG TIN PHẦN MỀM (giữ như cũ)
    # -----------------------------------------------------------------
    def _build_info(self):
        version_str = DEFAULT_VERSION
        # Đọc version.json từ đúng thư mục dữ liệu (run_app.py truyền qua biến môi trường TDM_APP_DATA_DIR)
        data_dir = os.environ.get("TDM_APP_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
        version_path = os.path.join(data_dir, "version.json")
        if os.path.exists(version_path):
            try:
                with open(version_path, "r", encoding="utf-8") as f:
                    version_str = json.load(f).get("version", version_str)
            except Exception:
                pass
        ctk.CTkLabel(self, text="ℹ️ Thông tin phần mềm & Bản quyền", font=FONT_H1).pack(anchor="w", padx=6, pady=(6, 16))
        info_box = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray95", "gray14"))
        info_box.pack(fill="x", padx=6, pady=(0, 16))
        ctk.CTkLabel(info_box, text="💊 Phần mềm TDM Aminoglycosid", font=FONT_H2).pack(anchor="w", padx=16, pady=(14, 6))
        for line in [
            f"•  Phiên bản hiện tại: {version_str}",
            f"•  Bản quyền sở hữu và phát triển: {COPYRIGHT_EMAIL}",
            "•  Cơ sở dữ liệu: Supabase Cloud Database",
        ]:
            ctk.CTkLabel(info_box, text=line, font=FONT_NORMAL, anchor="w").pack(anchor="w", padx=16, pady=2)
        ctk.CTkLabel(info_box, text="", font=FONT_NORMAL).pack(pady=(0, 6))
        guide_box = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray95", "gray14"))
        guide_box.pack(fill="x", padx=6)
        ctk.CTkLabel(guide_box, text="📖 Hướng dẫn sử dụng nhanh", font=FONT_H2).pack(anchor="w", padx=16, pady=(14, 6))
        guide_text = (
            "1. Tab Tính toán & TDM:\n"
            "   • Nhập thông tin hành chính bệnh nhân và thông số quần thể.\n"
            "   • Sawchuk–Zaske: tính cá thể hóa từ 2 mức nồng độ máu (C1, C2) của từng liều.\n"
            "   • Bayesian: chọn mô hình quần thể (tự động hoặc thủ công), nhập SCr, lịch sử liều và\n"
            "     nồng độ đo được; phần mềm ước lượng thông số cá thể và đề xuất liều mới.\n"
            "   • Lưu dữ liệu an toàn lên Cloud.\n\n"
            "2. Tab CSDL Bệnh nhân (Cloud):\n"
            "   • Tra cứu thông tin và lịch sử điều trị TDM của bệnh nhân theo Mã số y tế (MSYT).\n"
            "   • Hỗ trợ xóa từng block TDM theo ngày hoặc xóa toàn bộ hồ sơ khi cần thiết.\n\n"
            "3. Quên mật khẩu: liên hệ quản trị viên (Admin) để được đặt lại mật khẩu."
        )
        textbox = ctk.CTkTextbox(guide_box, height=230, font=FONT_NORMAL, wrap="word")
        textbox.pack(fill="x", padx=16, pady=(0, 16))
        textbox.insert("1.0", guide_text)
        textbox.configure(state="disabled")

    # -----------------------------------------------------------------
    # QUẢN TRỊ TÀI KHOẢN (chỉ admin)
    # -----------------------------------------------------------------
    def _build_admin(self):
        box = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray95", "gray14"))
        box.pack(fill="x", padx=6, pady=(16, 16))
        ctk.CTkLabel(box, text="🔐 Quản trị tài khoản (chỉ Admin)", font=FONT_H2).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(box, text="Mật khẩu được băm (bcrypt) trên Supabase — phần mềm và quản trị viên không xem được "
                               "mật khẩu cũ. Khi người dùng quên mật khẩu: đặt mật khẩu tạm mới và báo cho họ.",
                     font=FONT_SMALL, text_color=("gray40", "gray70"), wraplength=900, justify="left"
                     ).pack(anchor="w", padx=16, pady=(0, 8))

        # --- Danh sách tài khoản
        ctk.CTkLabel(box, text="A. Danh sách tài khoản", font=FONT_SMALL, text_color=("gray30", "gray80")
                     ).pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkButton(box, text="🔄 Tải danh sách tài khoản", height=30, width=190,
                      command=self.refresh_users).pack(anchor="w", padx=16)
        self.users_tree = ttk.Treeview(box, show="headings", height=6, selectmode="browse")
        self.users_tree["columns"] = ["user", "name", "role"]
        for col, title, w in (("user", "Tên đăng nhập", 180), ("name", "Họ tên", 260), ("role", "Vai trò", 120)):
            self.users_tree.heading(col, text=title)
            self.users_tree.column(col, width=w, anchor="w")
        self.users_tree.pack(fill="x", padx=16, pady=(6, 2))
        self.users_tree.bind("<<TreeviewSelect>>", self._on_select_user)
        self.users_status = StatusLabel(box)
        self.users_status.pack(fill="x", padx=16, pady=(0, 10))

        # --- Cấp tài khoản mới
        ctk.CTkLabel(box, text="B. Cấp tài khoản mới", font=FONT_SMALL, text_color=("gray30", "gray80")
                     ).pack(anchor="w", padx=16, pady=(8, 4))
        g = ctk.CTkFrame(box, fg_color="transparent")
        g.pack(fill="x", padx=12)
        g.grid_columnconfigure((0, 1, 2), weight=1, uniform="adm")
        self.new_user_entry = LabeledEntry(g, "Tên đăng nhập")
        self.new_user_entry.grid(row=0, column=0, sticky="ew", padx=4)
        self.new_name_entry = LabeledEntry(g, "Họ tên")
        self.new_name_entry.grid(row=0, column=1, sticky="ew", padx=4)
        role_frame = ctk.CTkFrame(g, fg_color="transparent")
        role_frame.grid(row=0, column=2, sticky="ew", padx=4)
        ctk.CTkLabel(role_frame, text="Vai trò", font=FONT_SMALL, anchor="w").pack(anchor="w")
        self.new_role_var = ctk.StringVar(value="")
        # Chỉ chọn trong các vai trò ĐANG CÓ (tránh gõ sai tên vai trò)
        self.new_role_combo = ctk.CTkOptionMenu(role_frame, values=[""], variable=self.new_role_var)
        self.new_role_combo.pack(fill="x", pady=(2, 4))
        self.new_pw_entry = LabeledEntry(g, f"Mật khẩu (≥ {MIN_PASSWORD_LEN} ký tự)")
        self.new_pw_entry.grid(row=1, column=0, sticky="ew", padx=4)
        self.new_pw2_entry = LabeledEntry(g, "Nhập lại mật khẩu")
        self.new_pw2_entry.grid(row=1, column=1, sticky="ew", padx=4)
        for w in (self.new_pw_entry, self.new_pw2_entry):
            w.entry.configure(show="•")
        ctk.CTkButton(g, text="🎲 Tạo mật khẩu ngẫu nhiên", height=30,
                      command=lambda: self._fill_random(self.new_pw_entry, self.new_pw2_entry, self.new_pw_show)
                      ).grid(row=1, column=2, sticky="ew", padx=4, pady=(18, 4))
        self.new_pw_show = ctk.CTkLabel(box, text="", font=FONT_SMALL, text_color=("#0969da", "#58a6ff"))
        self.new_pw_show.pack(anchor="w", padx=16)
        ctk.CTkButton(box, text="➕ Cấp tài khoản", height=34, fg_color="#2f6f4f", hover_color="#254f39",
                      command=self.add_user).pack(anchor="w", padx=16, pady=(6, 2))
        self.add_status = StatusLabel(box)
        self.add_status.pack(fill="x", padx=16, pady=(0, 10))

        # --- Đặt lại mật khẩu
        ctk.CTkLabel(box, text="C. Đặt lại mật khẩu (người dùng quên mật khẩu)", font=FONT_SMALL,
                     text_color=("gray30", "gray80")).pack(anchor="w", padx=16, pady=(8, 4))
        r = ctk.CTkFrame(box, fg_color="transparent")
        r.pack(fill="x", padx=12)
        r.grid_columnconfigure((0, 1, 2), weight=1, uniform="adm2")
        uf = ctk.CTkFrame(r, fg_color="transparent")
        uf.grid(row=0, column=0, sticky="ew", padx=4)
        ctk.CTkLabel(uf, text="Tài khoản (chọn ở danh sách A hoặc ở đây)", font=FONT_SMALL, anchor="w").pack(anchor="w")
        self.reset_user_var = ctk.StringVar(value="")
        self.reset_user_menu = ctk.CTkOptionMenu(uf, values=[""], variable=self.reset_user_var)
        self.reset_user_menu.pack(fill="x", pady=(2, 4))
        self.reset_pw_entry = LabeledEntry(r, f"Mật khẩu mới (≥ {MIN_PASSWORD_LEN} ký tự)")
        self.reset_pw_entry.grid(row=0, column=1, sticky="ew", padx=4)
        self.reset_pw2_entry = LabeledEntry(r, "Nhập lại mật khẩu mới")
        self.reset_pw2_entry.grid(row=0, column=2, sticky="ew", padx=4)
        for w in (self.reset_pw_entry, self.reset_pw2_entry):
            w.entry.configure(show="•")
        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(4, 2))
        ctk.CTkButton(btns, text="🎲 Tạo mật khẩu tạm", height=30, width=170,
                      command=lambda: self._fill_random(self.reset_pw_entry, self.reset_pw2_entry, self.reset_pw_show)
                      ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="🔑 Đặt lại mật khẩu", height=34, width=170, fg_color="#bf8700", hover_color="#9a6700",
                      command=self.reset_password).pack(side="left")
        self.reset_pw_show = ctk.CTkLabel(box, text="", font=FONT_SMALL, text_color=("#0969da", "#58a6ff"))
        self.reset_pw_show.pack(anchor="w", padx=16)
        self.reset_status = StatusLabel(box)
        self.reset_status.pack(fill="x", padx=16, pady=(0, 16))

        self.refresh_users()

    # --- tiện ích
    def _fill_random(self, e1, e2, show_label):
        pw = generate_password()
        e1.set(pw)
        e2.set(pw)
        show_label.configure(text=f"Mật khẩu tạm: {pw}   (ghi lại và báo cho người dùng; nên đổi sau khi đăng nhập)")

    def _on_select_user(self, event=None):
        sel = self.users_tree.selection()
        if sel:
            vals = self.users_tree.item(sel[0], "values")
            if vals:
                self.reset_user_var.set(vals[0])

    # --- thao tác
    def refresh_users(self):
        ok, data = db.admin_list_users()
        self.users_tree.delete(*self.users_tree.get_children())
        if not ok:
            self._users = []
            self.users_status.show(f"❌ {data}", "error")
            return
        self._users = data
        for u, name, role in data:
            self.users_tree.insert("", "end", values=(u, name, role))
        names = [u for u, _, _ in data] or [""]
        self.reset_user_menu.configure(values=names)
        if self.reset_user_var.get() not in names:
            self.reset_user_var.set("")
        roles = sorted({role for _, _, role in data if role})
        non_admin = [x for x in roles if x.lower() != ADMIN_ROLE]
        self.new_role_combo.configure(values=non_admin + [x for x in roles if x.lower() == ADMIN_ROLE] or [""])
        if not self.new_role_var.get():
            self.new_role_var.set(non_admin[0] if non_admin else "")
        self.users_status.show(f"✅ {len(data)} tài khoản.", "success")

    def add_user(self):
        u = self.new_user_entry.get().strip()
        name = self.new_name_entry.get().strip()
        role = self.new_role_var.get().strip()
        pw, pw2 = self.new_pw_entry.get(), self.new_pw2_entry.get()
        err = validate_username(u) or (None if name else "Chưa nhập họ tên.") or \
            (None if role else "Chưa chọn vai trò.") or validate_new_password(pw, pw2)
        if not err and any(x.lower() == u.lower() for x, _, _ in self._users):
            err = f"Tên đăng nhập '{u}' đã tồn tại."
        if err:
            self.add_status.show(f"⚠️ {err}", "warning")
            return
        if role.lower() == ADMIN_ROLE and not messagebox.askyesno(
                "Xác nhận", f"Cấp tài khoản '{u}' với vai trò ADMIN (toàn quyền quản trị tài khoản)?"):
            return
        ok, msg = db.admin_add_user(u, pw, name, role)
        if ok:
            self.add_status.show(f"✅ {msg}", "success")
            for w in (self.new_user_entry, self.new_name_entry, self.new_pw_entry, self.new_pw2_entry):
                w.set("")
            self.refresh_users()
        else:
            self.add_status.show(f"❌ {msg}", "error")

    def reset_password(self):
        u = self.reset_user_var.get().strip()
        pw, pw2 = self.reset_pw_entry.get(), self.reset_pw2_entry.get()
        err = (None if u else "Chưa chọn tài khoản.") or validate_new_password(pw, pw2)
        if err:
            self.reset_status.show(f"⚠️ {err}", "warning")
            return
        own = (u == db.current_session_user())
        q = (f"Đặt lại mật khẩu cho CHÍNH tài khoản đang đăng nhập '{u}'?" if own
             else f"Đặt lại mật khẩu cho tài khoản '{u}'? Mật khẩu cũ sẽ không dùng được nữa.")
        if not messagebox.askyesno("Xác nhận", q):
            return
        ok, msg = db.admin_reset_password(u, pw)
        if ok:
            self.reset_status.show(f"✅ {msg}", "success")
            self.reset_pw_entry.set("")
            self.reset_pw2_entry.set("")
        else:
            self.reset_status.show(f"❌ {msg}", "error")

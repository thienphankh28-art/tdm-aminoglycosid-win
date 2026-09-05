"""
tab3_info.py — Tab "Thông tin phần mềm": thông tin bản quyền, phiên bản, hướng dẫn liên hệ.

Tách riêng khỏi app.py để phát triển/bảo trì độc lập với các tab khác.
"""

import os
import json

import customtkinter as ctk

from ui_common import FONT_H1, FONT_H2, FONT_NORMAL, COPYRIGHT_EMAIL, DEFAULT_VERSION


class Tab3InfoFrame(ctk.CTkScrollableFrame):

    def __init__(self, master, app):

        super().__init__(master, fg_color="transparent")



        version_str = DEFAULT_VERSION

        # Đọc version.json từ đúng thư mục dữ liệu (được run_app.py truyền qua biến

        # môi trường TDM_APP_DATA_DIR) thay vì thư mục làm việc hiện tại (cwd), vì

        # cwd có thể khác nơi thực sự chứa file version.json vừa được cập nhật —

        # trước đây điều này khiến Tab này luôn hiển thị phiên bản cũ dù đã cập nhật.

        data_dir = os.environ.get("TDM_APP_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))

        version_path = os.path.join(data_dir, "version.json")

        if os.path.exists(version_path):

            try:

                with open(version_path, "r", encoding="utf-8") as f:

                    v_data = json.load(f)

                    version_str = v_data.get("version", version_str)

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

        guide_box.pack(fill="both", expand=True, padx=6)

        ctk.CTkLabel(guide_box, text="📖 Hướng dẫn sử dụng nhanh", font=FONT_H2).pack(anchor="w", padx=16, pady=(14, 6))



        guide_text = (

            "1. Tab Tính toán & TDM:\n"

            "   • Nhập thông tin hành chính bệnh nhân và thông số quần thể.\n"

            "   • Thực hiện tính toán cá thể hóa dựa trên 2 mức nồng độ máu (C1, C2).\n"

            "   • Hiệu chỉnh liều mới, xem trực quan biểu đồ nồng độ tích lũy qua nhiều\n"

            "     chu kỳ liều và lưu dữ liệu an toàn lên Cloud.\n\n"

            "2. Tab CSDL Bệnh nhân (Cloud):\n"

            "   • Tra cứu toàn bộ thông tin và lịch sử điều trị TDM của bệnh nhân theo\n"

            "     Mã số y tế (MSYT).\n"

            "   • Hỗ trợ xóa từng block TDM theo ngày hoặc xóa toàn bộ hồ sơ bệnh nhân\n"

            "     trên hệ thống đám mây khi cần thiết."

        )

        textbox = ctk.CTkTextbox(guide_box, height=260, font=FONT_NORMAL, wrap="word")

        textbox.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        textbox.insert("1.0", guide_text)

        textbox.configure(state="disabled")





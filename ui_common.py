"""
ui_common.py — Hằng số cấu hình chung, hàm tiện ích và các widget CustomTkinter tái sử dụng
(LabeledEntry, LabeledOption, LabeledCheck, MetricCard, StatusLabel) dùng CHUNG cho mọi tab
của phần mềm TDM Aminoglycosid / Vancomycin.

File này được TÁCH RA từ app.py (trước đây gần 4000 dòng) để mỗi tab (Tab1..Tab4) có thể
phát triển độc lập trong file riêng của mình mà không sợ đụng/va chạm code của nhau.
KHÔNG có logic nghiệp vụ (tính toán PK, gọi Cloud) ở đây — chỉ thuần UI dùng chung.
"""

import datetime
import unicodedata

import customtkinter as ctk


# =============================================================================
# CẤU HÌNH GIAO DIỆN CHUNG
# =============================================================================
COPYRIGHT_EMAIL = "thienphankh28@gmail.com"
DEFAULT_VERSION = "V.1.0.8"

FONT_H1 = ("Segoe UI", 20, "bold")
FONT_H2 = ("Segoe UI", 15, "bold")
FONT_NORMAL = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 11)


# =============================================================================
# HÀM TIỆN ÍCH DÙNG CHUNG
# =============================================================================
def parse_float(value, default=0.0):

    """Chuyển chuỗi nhập từ Entry thành float an toàn (tương đương st.number_input)"""

    try:

        return float(str(value).replace(",", ".").strip())

    except Exception:

        return default





def clean_vn_text(text):

    """Loại bỏ dấu tiếng Việt để xuất PDF bằng font Arial chuẩn của FPDF"""

    if text is None:

        return ""

    nfkd_form = unicodedata.normalize("NFKD", str(text))

    result = "".join([c for c in nfkd_form if not unicodedata.combining(c)])

    return result.replace("đ", "d").replace("Đ", "D")





def today_str():

    return datetime.date.today().strftime("%Y-%m-%d")





def parse_date(value):

    """Parse chuỗi ngày dạng YYYY-MM-DD, trả về datetime.date; lỗi -> hôm nay"""

    try:

        return datetime.datetime.strptime(value.strip(), "%Y-%m-%d").date()

    except Exception:

        return datetime.date.today()






# =============================================================================
# CÁC WIDGET TÁI SỬ DỤNG (thay thế st.number_input / st.metric / ...)
# =============================================================================
class LabeledEntry(ctk.CTkFrame):

    """Nhãn + ô nhập liệu, tương đương st.number_input / st.text_input"""



    def __init__(self, master, label, default="", **kwargs):

        super().__init__(master, fg_color="transparent", **kwargs)

        ctk.CTkLabel(self, text=label, anchor="w", font=FONT_SMALL,

                     text_color=("gray20", "gray85")).pack(anchor="w")

        self.var = ctk.StringVar(value=str(default))

        self.entry = ctk.CTkEntry(self, textvariable=self.var)

        self.entry.pack(fill="x", pady=(2, 4))



    def get(self):

        return self.var.get()



    def get_float(self, default=0.0):

        return parse_float(self.var.get(), default)



    def set(self, value):

        self.var.set("" if value is None else str(value))





class LabeledOption(ctk.CTkFrame):

    """Nhãn + Combobox, tương đương st.selectbox"""



    def __init__(self, master, label, values, default=None, **kwargs):

        super().__init__(master, fg_color="transparent", **kwargs)

        ctk.CTkLabel(self, text=label, anchor="w", font=FONT_SMALL,

                     text_color=("gray20", "gray85")).pack(anchor="w")

        self.var = ctk.StringVar(value=default or values[0])

        self.combo = ctk.CTkOptionMenu(self, values=values, variable=self.var)

        self.combo.pack(fill="x", pady=(2, 4))



    def get(self):

        return self.var.get()



    def set(self, value):

        if value:

            self.var.set(value)





class LabeledCheck(ctk.CTkFrame):

    """Checkbox có nhãn, tương đương st.checkbox"""



    def __init__(self, master, label, default=False, **kwargs):

        super().__init__(master, fg_color="transparent", **kwargs)

        self.var = ctk.BooleanVar(value=bool(default))

        self.check = ctk.CTkCheckBox(self, text=label, variable=self.var, font=FONT_SMALL)

        self.check.pack(anchor="w", pady=4)



    def get(self):

        return self.var.get()



    def set(self, value):

        self.var.set(bool(value))





class MetricCard(ctk.CTkFrame):

    """Thẻ hiển thị số liệu, tương đương st.metric()"""



    def __init__(self, master, title, value="--", **kwargs):

        super().__init__(master, corner_radius=10, fg_color=("gray92", "gray17"), **kwargs)

        ctk.CTkLabel(self, text=title, font=FONT_SMALL,

                     text_color=("gray40", "gray70")).pack(anchor="w", padx=12, pady=(8, 0))

        self.value_label = ctk.CTkLabel(self, text=value, font=("Segoe UI", 18, "bold"))

        self.value_label.pack(anchor="w", padx=12, pady=(0, 10))



    def set_value(self, value):

        self.value_label.configure(text=value)





class StatusLabel(ctk.CTkLabel):

    """Nhãn hiển thị thông báo success/error/warning/info thay cho st.success/error..."""



    COLORS = {

        "success": "#1a7f37",

        "error": "#d1242f",

        "warning": "#9a6700",

        "info": "#0969da",

    }



    def __init__(self, master, **kwargs):

        super().__init__(master, text="", font=FONT_SMALL, justify="left",

                          anchor="w", wraplength=560, **kwargs)



    def show(self, message, kind="info"):

        self.configure(text=message, text_color=self.COLORS.get(kind, "#0969da"))





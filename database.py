"""
database.py — Quản lý toàn bộ dữ liệu trên Supabase Cloud (User, Bệnh nhân & Lịch sử TDM)

Phiên bản dành cho ứng dụng Desktop (CustomTkinter): đã loại bỏ hoàn toàn phụ thuộc
vào streamlit. Kết nối Supabase được cache thủ công bằng biến singleton thay cho
@st.cache_resource, và lỗi được ghi ra log (module `logging`) thay vì st.error().

Các hàm ghi/xóa/import dữ liệu (save_*, delete_*, import_*) trả về tuple
(success: bool, message: str) để lớp giao diện (app.py) tự quyết định cách hiển thị
thông báo cho người dùng — thay vì phụ thuộc vào cơ chế toast toàn cục của Streamlit.
"""

import logging

import pandas as pd
from supabase import create_client, Client

# ==========================================
# 0. CẤU HÌNH LOGGING
# ==========================================
logger = logging.getLogger("tdm_aminoglycosid.database")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", "%H:%M:%S"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# ==========================================
# 1. CẤU HÌNH KẾT NỐI SUPABASE CLOUD
# ==========================================
SUPABASE_URL = "https://hgcetesvtjmkvpdjqdgx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhnY2V0ZXN2dGpta3ZwZGpxZGd4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODcyNDc3NDQsImV4cCI6MjEwMjgyMzc0NH0.e-8VsaqaTfpUYwuFptdn6Kia7Yx28CJjgFKbPDwrFDI"

_supabase_client: "Client | None" = None


def init_supabase():
    """
    Khởi tạo (hoặc tái sử dụng) kết nối Supabase Client.
    Thay thế cho @st.cache_resource của Streamlit bằng một singleton thủ công đơn
    giản: vì app desktop chỉ import module này một lần khi khởi động nên client chỉ
    cần được tạo đúng một lần trong suốt vòng đời ứng dụng.
    """
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    try:
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Đã kết nối thành công tới Supabase Cloud.")
        return _supabase_client
    except Exception as e:
        logger.error(f"Không thể kết nối Supabase Cloud: {e}")
        return None


def reconnect_supabase():
    """Buộc tạo lại kết nối Supabase (dùng khi cần 'kết nối lại' thủ công từ giao diện)."""
    global _supabase_client
    _supabase_client = None
    return init_supabase()


supabase = init_supabase()

# ==========================================
# 2. QUẢN LÝ TÀI KHOẢN NGƯỜI DÙNG (Bảng 'Users')
# ==========================================
def check_login(username, password):
    if not supabase:
        return None
    try:
        response = (supabase.table("Users").select("fullname, role")
                    .eq("Username", username).eq("Password", password).execute())
        data = response.data
        if data and len(data) > 0:
            return data[0]['fullname'], data[0]['role']
        return None
    except Exception as e:
        logger.error(f"Lỗi đăng nhập: {e}")
        return None

def add_user(username, password, fullname, role):
    if not supabase:
        return False, "Chưa kết nối được Cloud Database!"
    try:
        data = {"Username": username, "Password": password, "fullname": fullname, "role": role}
        supabase.table("Users").insert(data).execute()
        return True, "Cấp tài khoản mới thành công!"
    except Exception as e:
        logger.error(f"Lỗi cấp tài khoản: {e}")
        return False, f"Lỗi: Tên đăng nhập đã tồn tại ({e})"

def get_all_users():
    if not supabase:
        return []
    try:
        response = supabase.table("Users").select("Username, fullname, role").execute()
        return [(u['Username'], u['fullname'], u['role']) for u in response.data]
    except Exception as e:
        logger.error(f"Lỗi tải danh sách người dùng: {e}")
        return []

def delete_user(username):
    if username == 'admin':
        return False, "Không thể xóa tài khoản Admin gốc!"
    if not supabase:
        return False, "Chưa kết nối Cloud!"
    try:
        supabase.table("Users").delete().eq("Username", username).execute()
        return True, "Đã xóa tài khoản thành công!"
    except Exception as e:
        logger.error(f"Lỗi xóa tài khoản: {e}")
        return False, f"Lỗi khi xóa: {e}"


# ==========================================
# 3. QUẢN LÝ DỮ LIỆU BỆNH NHÂN & TDM TRÊN CLOUD
# ==========================================
def init_db():
    """Hàm giữ nguyên tương thích (Supabase tự quản lý qua SQL Editor)"""
    pass

def get_latest_tdm(msyt):
    """Lấy dữ liệu thông tin bệnh nhân và lần TDM gần nhất từ Supabase"""
    if not supabase:
        return None, None
    try:
        p_res = supabase.table("patients").select("*").eq("msyt", msyt).execute()
        if not p_res.data:
            return None, None
        patient = p_res.data[0]

        t_res = (supabase.table("tdm_history").select("*").eq("msyt", msyt)
                 .order("tdm_date", desc=True).limit(1).execute())
        latest_tdm = t_res.data[0] if t_res.data else None

        return patient, latest_tdm
    except Exception as e:
        logger.error(f"Lỗi tải dữ liệu bệnh nhân {msyt}: {e}")
        return None, None

def check_tdm_exists(msyt, date_str):
    if not supabase:
        return False
    try:
        res = supabase.table("tdm_history").select("msyt").eq("msyt", msyt).eq("tdm_date", date_str).execute()
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"Lỗi kiểm tra block TDM: {e}")
        return False

def save_sec3_data(msyt, date_str, scr, t1, c1, t2, c2, ke, t_half, vd, true_peak, true_trough):
    """Lưu kết quả cá thể hóa (Mục 3). Trả về (success, message)."""
    if not supabase:
        return False, "Chưa kết nối được Cloud Database!"
    try:
        data = {
            "msyt": msyt, "tdm_date": date_str, "scr": scr,
            "t1": t1, "c1": c1, "t2": t2, "c2": c2,
            "ke": ke, "t_half": t_half, "vd": vd,
            "true_peak": true_peak, "true_trough": true_trough
        }
        if check_tdm_exists(msyt, date_str):
            supabase.table("tdm_history").update(data).eq("msyt", msyt).eq("tdm_date", date_str).execute()
        else:
            supabase.table("tdm_history").insert(data).execute()
        return True, f"Đã lưu block TDM lên Cloud cho ngày {date_str}."
    except Exception as e:
        logger.error(f"Lỗi lưu dữ liệu Mục 3 lên Cloud: {e}")
        return False, f"Lỗi lưu dữ liệu lên Cloud: {e}"

def save_sec4_data(msyt, date_str, new_dose, new_tau, new_t_inf, pred_cp, pred_ctrough):
    """Lưu phác đồ hiệu chỉnh liều mới (Mục 4). Trả về (success, message)."""
    if not supabase:
        return False, "Chưa kết nối được Cloud Database!"
    try:
        data = {
            "new_dose": new_dose, "new_tau": new_tau, "new_t_inf": new_t_inf,
            "pred_cp": pred_cp, "pred_ctrough": pred_ctrough
        }
        if check_tdm_exists(msyt, date_str):
            supabase.table("tdm_history").update(data).eq("msyt", msyt).eq("tdm_date", date_str).execute()
        else:
            data.update({"msyt": msyt, "tdm_date": date_str})
            supabase.table("tdm_history").insert(data).execute()
        return True, f"Đã lưu phác đồ mới lên Cloud block ngày {date_str}."
    except Exception as e:
        logger.error(f"Lỗi lưu dữ liệu Mục 4 lên Cloud: {e}")
        return False, f"Lỗi lưu dữ liệu lên Cloud: {e}"

def delete_patient(msyt):
    """Xóa vĩnh viễn bệnh nhân + toàn bộ lịch sử TDM. Trả về (success, message)."""
    if not supabase:
        return False, "Chưa kết nối Cloud!"
    try:
        supabase.table("tdm_history").delete().eq("msyt", msyt).execute()
        supabase.table("patients").delete().eq("msyt", msyt).execute()
        return True, f"Đã xóa bệnh nhân {msyt} khỏi Cloud!"
    except Exception as e:
        logger.error(f"Lỗi khi xóa bệnh nhân {msyt}: {e}")
        return False, f"Lỗi khi xóa bệnh nhân: {e}"

def delete_tdm_block(msyt, tdm_date):
    """Xóa một block TDM theo ngày. Trả về (success, message)."""
    if not supabase:
        return False, "Chưa kết nối Cloud!"
    try:
        supabase.table("tdm_history").delete().eq("msyt", msyt).eq("tdm_date", tdm_date).execute()
        return True, f"Đã xóa thành công block TDM ngày {tdm_date}!"
    except Exception as e:
        logger.error(f"Lỗi khi xóa block TDM {msyt}/{tdm_date}: {e}")
        return False, f"Lỗi khi xóa ca TDM: {e}"

def get_all_patients_dataframe():
    if not supabase:
        return pd.DataFrame()
    try:
        res = supabase.table("patients").select("*").execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        logger.error(f"Lỗi tải danh sách bệnh nhân: {e}")
        return pd.DataFrame()

def get_all_tdm_blocks_dataframe():
    if not supabase:
        return pd.DataFrame()
    try:
        res = supabase.table("tdm_history").select("*").execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        logger.error(f"Lỗi tải danh sách block TDM: {e}")
        return pd.DataFrame()

def import_patients_from_dataframe(df):
    """Nhập hàng loạt bệnh nhân từ DataFrame (upsert). Trả về (success, message)."""
    if not supabase:
        return False, "Chưa kết nối Cloud!"
    if df is None or df.empty:
        return False, "Dữ liệu nhập vào trống, không có gì để import."
    try:
        for _, row in df.iterrows():
            supabase.table("patients").upsert(row.to_dict()).execute()
        return True, f"Đã import thành công {len(df)} bệnh nhân."
    except Exception as e:
        logger.error(f"Lỗi import bệnh nhân: {e}")
        return False, f"Lỗi import bệnh nhân: {e}"

def import_tdm_blocks_from_dataframe(df):
    """Nhập hàng loạt block TDM từ DataFrame (upsert). Trả về (success, message)."""
    if not supabase:
        return False, "Chưa kết nối Cloud!"
    if df is None or df.empty:
        return False, "Dữ liệu nhập vào trống, không có gì để import."
    try:
        for _, row in df.iterrows():
            supabase.table("tdm_history").upsert(row.to_dict()).execute()
        return True, f"Đã import thành công {len(df)} block TDM."
    except Exception as e:
        logger.error(f"Lỗi import TDM: {e}")
        return False, f"Lỗi import TDM: {e}"

def get_all_records():
    if not supabase:
        return pd.DataFrame()
    try:
        res = supabase.table("tdm_history").select("*").execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        logger.error(f"Lỗi tải toàn bộ bản ghi TDM: {e}")
        return pd.DataFrame()

# ==========================================
# 4. HÀM HỖ TRỢ BỔ SUNG CHO GIAO DIỆN (APP.PY)
# ==========================================
def save_patient_info(msyt, gender, weight, height, age, is_cf):
    """Lưu hoặc cập nhật thông tin hành chính bệnh nhân lên Cloud. Trả về (success, message)."""
    if not supabase:
        return False, "Chưa kết nối được Cloud Database!"
    try:
        data = {
            "msyt": msyt, "gender": gender, "weight": weight,
            "height": height, "age": age, "is_cf": int(is_cf)
        }
        supabase.table("patients").upsert(data).execute()
        return True, "Đã lưu thông tin bệnh nhân lên Cloud."
    except Exception as e:
        logger.error(f"Lỗi lưu thông tin bệnh nhân {msyt}: {e}")
        return False, f"Lỗi lưu thông tin bệnh nhân lên Cloud: {e}"

def get_patient_by_msyt(msyt):
    """Lấy DataFrame thông tin 1 bệnh nhân theo MSYT"""
    if not supabase:
        return pd.DataFrame()
    try:
        res = supabase.table("patients").select("*").eq("msyt", msyt).execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        logger.error(f"Lỗi tải thông tin bệnh nhân {msyt}: {e}")
        return pd.DataFrame()

def get_history_by_msyt(msyt):
    """Lấy DataFrame lịch sử TDM của 1 bệnh nhân theo MSYT"""
    if not supabase:
        return pd.DataFrame()
    try:
        res = supabase.table("tdm_history").select("*").eq("msyt", msyt).execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        logger.error(f"Lỗi tải lịch sử TDM của {msyt}: {e}")
        return pd.DataFrame()

def get_specific_tdm_block(msyt, date_str):
    """Lấy chi tiết 1 block TDM theo MSYT và ngày"""
    if not supabase:
        return None
    try:
        res = supabase.table("tdm_history").select("*").eq("msyt", msyt).eq("tdm_date", date_str).execute()
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        logger.error(f"Lỗi tải block TDM {msyt}/{date_str}: {e}")
        return None

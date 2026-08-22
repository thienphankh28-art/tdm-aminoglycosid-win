import sys
import os
import json
import re
import shutil
import requests

# ==========================================
# THÔNG TIN BẢN QUYỀN PHẦN MỀM
# ==========================================
COPYRIGHT_EMAIL = "thienphankh28@gmail.com"

GITHUB_VERSION_URL = "https://raw.githubusercontent.com/thienphankh28-art/tdm-aminoglycosid/refs/heads/main/version.json"
GITHUB_CODE_BASE_URL = "https://raw.githubusercontent.com/thienphankh28-art/tdm-aminoglycosid/main/"

FILES_TO_UPDATE = ["app.py", "database.py", "pk_calculations.py", "version.json"]

# Xác định thư mục chứa file .exe ngoài đời thực
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = sys._MEIPASS  # Thư mục tạm bên trong .exe
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = BASE_DIR

LOCAL_VERSION_FILE = os.path.join(BASE_DIR, "version.json")

# ---------------------------------------------------------
# BỘ KHỞI TẠO (BOOTSTRAP): Tự trích xuất file nếu chạy lần đầu
# ---------------------------------------------------------
if getattr(sys, 'frozen', False):
    for file_name in FILES_TO_UPDATE:
        target_path = os.path.join(BASE_DIR, file_name)
        if not os.path.exists(target_path):
            source_path = os.path.join(BUNDLE_DIR, file_name)
            if os.path.exists(source_path):
                shutil.copy(source_path, target_path)

def get_local_version():
    if os.path.exists(LOCAL_VERSION_FILE):
        try:
            with open(LOCAL_VERSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("version", "1.0.0")
        except Exception:
            pass
    return "1.0.0"

def parse_version(version_str):
    try:
        numbers = re.findall(r'\d+', str(version_str))
        if numbers:
            return tuple(map(int, numbers))
        return (0, 0, 0)
    except Exception:
        return (0, 0, 0)

def check_and_update():
    current_version = get_local_version()
    print(f"==================================================")
    print(f"  PHẦN MỀM TDM AMINOGLYCOSID - v{current_version}")
    print(f"  Bản quyền thuộc về: {COPYRIGHT_EMAIL}")
    print(f"==================================================")
    print("Đang kiểm tra cập nhật từ máy chủ...")
    try:
        response = requests.get(GITHUB_VERSION_URL, timeout=3)
        if response.status_code == 200:
            remote_data = response.json()
            remote_version_str = remote_data.get("version", current_version)

            if parse_version(remote_version_str) > parse_version(current_version):
                print(f"✨ Phát hiện phiên bản mới: {remote_version_str}. Đang tiến hành cập nhật...")
                for file_name in FILES_TO_UPDATE:
                    file_url = GITHUB_CODE_BASE_URL + file_name
                    file_res = requests.get(file_url, timeout=5)
                    if file_res.status_code == 200:
                        target_path = os.path.join(BASE_DIR, file_name)
                        # Ép buộc đồng bộ chuẩn xuống dòng Windows (CRLF) tránh lỗi Mixed Newlines
                        with open(target_path, "w", encoding="utf-8") as fw:
                            lines = file_res.text.splitlines()
                            fw.write("\r\n".join(lines) + "\r\n")
                        print(f"✅ Đã cập nhật xong file: {file_name}")
                    else:
                        print(f"❌ Không tải được file {file_name}")
                print("✅ Cập nhật phần mềm thành công!")
            else:
                print("ℹ️ Phần mềm đang ở phiên bản mới nhất.")
        else:
            print("ℹ️ Đang chạy ở chế độ ngoại tuyến.")
    except Exception as e:
        print(f"ℹ️ Lỗi kết nối cập nhật: {e}. Tiếp tục khởi chạy bình thường.")

def launch_desktop_app():
    """
    Sau khi tải/cập nhật code xong, import app.py (đã được ghi đè tại BASE_DIR nếu có
    cập nhật mới) và gọi trực tiếp hàm app.main() để khởi chạy giao diện Windows
    (CustomTkinter), KHÔNG còn phụ thuộc vào streamlit / subprocess nữa.
    """
    # Đảm bảo BASE_DIR (nơi chứa app.py có thể đã được cập nhật) được ưu tiên
    # tìm kiếm module trước cả thư mục bundle của PyInstaller.
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

    # Nếu app đã được import trước đó (ví dụ do bundle), xóa cache để đảm bảo
    # phiên bản mới nhất trên đĩa (BASE_DIR) được nạp lại.
    for mod_name in ("app", "database", "pk_calculations"):
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    import app  # noqa: E402  (import sau khi đã chỉnh sys.path)

    if hasattr(app, "main"):
        app.main()
    else:
        print("❌ Không tìm thấy hàm main() trong app.py. Không thể khởi chạy giao diện.")
        sys.exit(1)

if __name__ == "__main__":
    check_and_update()
    launch_desktop_app()

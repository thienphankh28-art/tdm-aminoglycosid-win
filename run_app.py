"""
run_app.py — Lõi kiểm tra/cập nhật phiên bản & khởi chạy giao diện Desktop (CustomTkinter).

File này có thể chạy theo 2 cách:
  1. Trực tiếp khi phát triển: `python run_app.py` (nằm cùng thư mục với app.py,
     database.py, pk_calculations.py, version.json). Hành vi giữ nguyên như cũ.
  2. Được launcher.py (bản .exe đóng gói) tải bản mới nhất về rồi exec() — khi đó
     launcher.py truyền sẵn biến toàn cục LAUNCHER_DATA_DIR trỏ tới một thư mục dữ
     liệu ỔN ĐỊNH và LUÔN GHI ĐƯỢC (%LOCALAPPDATA%\\TDM_Aminoglycosid), độc lập với
     nơi file .exe được cài đặt.

     Đây chính là chỗ sửa lỗi "kiểm tra thấy bản cập nhật nhưng không cập nhật
     được" sau khi đóng gói: trước đây BASE_DIR = thư mục chứa file .exe, nơi có
     thể KHÔNG có quyền ghi với user thường (Program Files, thư mục do OneDrive
     quản lý, v.v.) khiến bước ghi đè file mới bị lỗi âm thầm (do build dùng
     --noconsole nên không thấy lỗi). Giờ mọi thao tác đọc/ghi cập nhật đều diễn
     ra tại thư mục do launcher.py cung cấp, luôn ghi được.
"""

import sys
import os
import json
import re
import shutil
import datetime
import traceback
import requests

# ==========================================
# THÔNG TIN BẢN QUYỀN PHẦN MỀM
# ==========================================
COPYRIGHT_EMAIL = "thienphankh28@gmail.com"

GITHUB_VERSION_URL = "https://raw.githubusercontent.com/thienphankh28-art/tdm-aminoglycosid-win/refs/heads/main/version.json"
GITHUB_CODE_BASE_URL = "https://raw.githubusercontent.com/thienphankh28-art/tdm-aminoglycosid-win/main/"

FILES_TO_UPDATE = ["app.py", "database.py", "pk_calculations.py", "version.json", "run_app.py"]

# ---------------------------------------------------------
# XÁC ĐỊNH THƯ MỤC DỮ LIỆU (BASE_DIR) VÀ THƯ MỤC BUNDLE GỐC
# ---------------------------------------------------------
# Ưu tiên 1: launcher.py (bản .exe) đã tính sẵn 1 thư mục ổn định & luôn ghi được
# và truyền vào qua biến toàn cục này (xem launcher.py để biết chi tiết).
_launcher_data_dir = globals().get("LAUNCHER_DATA_DIR")

if _launcher_data_dir:
    BASE_DIR = _launcher_data_dir
    BUNDLE_DIR = sys._MEIPASS if getattr(sys, "frozen", False) else BASE_DIR
elif getattr(sys, "frozen", False):
    # Tương thích ngược: trường hợp run_app.py bị đóng gói làm entry-point trực
    # tiếp mà KHÔNG qua launcher.py (không khuyến khích — có thể gặp lại lỗi
    # quyền ghi nêu trên nếu thư mục cài đặt exe không cho phép user ghi).
    BASE_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = sys._MEIPASS
else:
    # Chạy trực tiếp bằng `python run_app.py` khi phát triển
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = BASE_DIR

os.makedirs(BASE_DIR, exist_ok=True)

LOCAL_VERSION_FILE = os.path.join(BASE_DIR, "version.json")
UPDATE_LOG_FILE = os.path.join(BASE_DIR, "update_log.txt")


def log_update(message):
    """
    Ghi log ra file thay vì chỉ print(), vì bản .exe build với --noconsole không
    có cửa sổ CMD để xem print() — nếu không ghi log, mọi lỗi cập nhật sẽ "biến
    mất" hoàn toàn và không có cách nào chẩn đoán được sự cố.
    """
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line)
    try:
        with open(UPDATE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------
# BỘ KHỞI TẠO (BOOTSTRAP): Tự trích xuất file nếu chạy lần đầu
# ---------------------------------------------------------
if BUNDLE_DIR != BASE_DIR:
    for file_name in FILES_TO_UPDATE:
        target_path = os.path.join(BASE_DIR, file_name)
        if not os.path.exists(target_path):
            source_path = os.path.join(BUNDLE_DIR, file_name)
            if os.path.exists(source_path):
                try:
                    shutil.copy(source_path, target_path)
                except Exception as e:
                    log_update(f"❌ Không thể trích xuất {file_name} từ bundle: {e}")


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
    log_update("==================================================")
    log_update(f"  PHẦN MỀM TDM AMINOGLYCOSID - v{current_version}")
    log_update(f"  Bản quyền thuộc về: {COPYRIGHT_EMAIL}")
    log_update(f"  Thư mục dữ liệu (BASE_DIR): {BASE_DIR}")
    log_update("==================================================")
    log_update("Đang kiểm tra cập nhật từ máy chủ...")

    try:
        response = requests.get(GITHUB_VERSION_URL, timeout=5)
    except Exception as e:
        log_update(f"ℹ️ Không có kết nối mạng để kiểm tra cập nhật ({e}). Tiếp tục khởi chạy với bản hiện có.")
        return

    if response.status_code != 200:
        log_update(f"ℹ️ Máy chủ trả về mã lỗi {response.status_code} khi kiểm tra phiên bản. Đang chạy ở chế độ ngoại tuyến.")
        return

    try:
        remote_data = response.json()
    except Exception as e:
        log_update(f"❌ Không đọc được version.json từ máy chủ: {e}")
        return

    remote_version_str = remote_data.get("version", current_version)
    if parse_version(remote_version_str) <= parse_version(current_version):
        log_update("ℹ️ Phần mềm đang ở phiên bản mới nhất.")
        return

    log_update(f"✨ Phát hiện phiên bản mới: {remote_version_str}. Đang tiến hành cập nhật...")

    all_ok = True
    for file_name in FILES_TO_UPDATE:
        try:
            file_res = requests.get(GITHUB_CODE_BASE_URL + file_name, timeout=10)
            if file_res.status_code != 200:
                all_ok = False
                log_update(f"❌ Không tải được file {file_name} (mã lỗi {file_res.status_code}).")
                continue

            target_path = os.path.join(BASE_DIR, file_name)
            # Ép buộc đồng bộ chuẩn xuống dòng Windows (CRLF) tránh lỗi Mixed Newlines
            lines = file_res.text.splitlines()
            with open(target_path, "w", encoding="utf-8") as fw:
                fw.write("\r\n".join(lines) + "\r\n")
            log_update(f"✅ Đã cập nhật xong file: {file_name}")
        except PermissionError as e:
            all_ok = False
            log_update(
                f"❌ KHÔNG CÓ QUYỀN GHI vào '{file_name}' tại thư mục '{BASE_DIR}'. "
                f"Hãy kiểm tra thư mục này có bị hệ thống/phần mềm diệt virus chặn ghi hay không. "
                f"Chi tiết lỗi: {e}")
        except Exception as e:
            all_ok = False
            log_update(f"❌ Lỗi khi cập nhật file {file_name}: {e}")

    if all_ok:
        log_update("✅ Cập nhật phần mềm thành công!")
    else:
        log_update("⚠️ Cập nhật KHÔNG hoàn tất — một số file cập nhật thất bại (xem chi tiết ở log phía trên).")

def launch_desktop_app():
    """
    Sau khi tải/cập nhật code xong, import app.py (đã được ghi đè tại BASE_DIR nếu có
    cập nhật mới) và gọi trực tiếp hàm app.main() để khởi chạy giao diện Windows
    (CustomTkinter), KHÔNG còn phụ thuộc vào streamlit / subprocess nữa.
    """
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

    # Nếu app đã được import trước đó (ví dụ do bundle), xóa cache để đảm bảo
    # phiên bản mới nhất trên đĩa (BASE_DIR) được nạp lại.
    for mod_name in ("app", "database", "pk_calculations"):
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    # Cho app.py biết chính xác thư mục dữ liệu đang dùng, để nó đọc đúng
    # version.json vừa được cập nhật (thay vì đọc nhầm theo thư mục làm việc
    # hiện tại lúc khởi chạy, vốn có thể khác thư mục dữ liệu thực sự).
    os.environ["TDM_APP_DATA_DIR"] = BASE_DIR

    try:
        import app
    except Exception:
        log_update("❌ Lỗi khi import app.py:\n" + traceback.format_exc())
        raise

    if hasattr(app, "main"):
        app.main()
    else:
        log_update("❌ Không tìm thấy hàm main() trong app.py. Không thể khởi chạy giao diện.")
        sys.exit(1)

if __name__ == "__main__":
    check_and_update()
    launch_desktop_app()

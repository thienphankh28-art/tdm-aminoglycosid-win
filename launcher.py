"""
launcher.py — Vỏ bọc khởi động (bootstrapper) cho file .exe đóng gói bằng PyInstaller.

*** VẤN ĐỀ ĐÃ SỬA TRONG BẢN NÀY ***
Trước khi đóng gói, chạy `python run_app.py` trực tiếp thì BASE_DIR = thư mục
chứa chính file run_app.py (thư mục code của bạn) -> luôn ghi được -> cập nhật
thành công. Sau khi đóng gói .exe, BASE_DIR = thư mục CÀI ĐẶT file .exe (vd.
Desktop do OneDrive đồng bộ, C:\\Program Files, v.v.). Bước KIỂM TRA phiên bản
chỉ đọc mạng nên vẫn chạy tốt, nhưng bước GHI ĐÈ file mới xuống thư mục đó có
thể bị Windows từ chối quyền ghi (PermissionError) — và vì build.py dùng
--noconsole nên lỗi này hoàn toàn vô hình với người dùng, tạo cảm giác
"kiểm tra được nhưng không cập nhật được".

Cách sửa: tách biệt hoàn toàn "nơi cài đặt exe" khỏi "nơi lưu dữ liệu có thể
ghi". Toàn bộ file có thể tự cập nhật (run_app.py, app.py, database.py,
pk_calculations.py, version.json) giờ được lưu tại:

    %LOCALAPPDATA%\\TDM_Aminoglycosid

Thư mục này luôn thuộc quyền sở hữu của user hiện tại trên Windows nên LUÔN ghi
được mà không cần quyền Admin, bất kể file .exe được cài ở đâu.

Nhiệm vụ của launcher.py:
 1. Xác định thư mục dữ liệu ổn định nói trên.
 2. Đảm bảo có sẵn 1 bản run_app.py dùng được trong thư mục đó (lần đầu tiên lấy
    từ chính trong exe qua sys._MEIPASS để chạy được cả khi KHÔNG có mạng; các
    lần sau ưu tiên tải bản mới nhất từ GitHub/jsdelivr).
 3. Nạp (exec) và chạy run_app.py — nơi đảm nhiệm việc kiểm tra & tải cập nhật
    app.py / database.py / pk_calculations.py / version.json, rồi khởi chạy
    giao diện CustomTkinter.
 4. Ghi log lỗi ra file (vì bản build --noconsole không có cửa sổ CMD để xem
    print()) để có thể chẩn đoán khi có sự cố.
"""

import sys
import os
import datetime
import traceback
import multiprocessing
import requests

APP_FOLDER_NAME = "TDM_Aminoglycosid"
RUN_APP_URL = "https://cdn.jsdelivr.net/gh/thienphankh28-art/tdm-aminoglycosid-win@main/run_app.py"


def get_data_dir():
    """
    Thư mục dữ liệu ổn định, LUÔN ghi được với quyền user thường, tách biệt hoàn
    toàn khỏi nơi cài đặt file .exe. Đây là nơi thực sự lưu run_app.py, app.py,
    database.py, pk_calculations.py, version.json và được cập nhật theo thời gian.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(base, APP_FOLDER_NAME)
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def log_error(data_dir, message):
    """Ghi lỗi ra file log.txt vì bản build --noconsole không có cửa sổ để xem print()."""
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    try:
        with open(os.path.join(data_dir, "launcher_error.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # Nếu ngay việc ghi log cũng lỗi thì đành chịu, không còn cách nào báo cho user


def ensure_local_run_app(data_dir):
    """
    Đảm bảo data_dir có sẵn 1 bản run_app.py dùng được:
      - Nếu chưa có, trích xuất từ bên trong file .exe (sys._MEIPASS) ra trước —
        đảm bảo LẦN CHẠY ĐẦU TIÊN, kể cả khi KHÔNG có mạng, phần mềm vẫn khởi
        chạy được bình thường.
      - Sau đó luôn thử tải bản run_app.py mới nhất từ GitHub (qua jsdelivr) để
        cập nhật chính logic khởi động/cập nhật, và CHỈ ghi đè khi tải thành công
        (tránh trường hợp tải lỗi/rớt mạng giữa chừng làm hỏng file đang dùng tốt).
    """
    target_path = os.path.join(data_dir, "run_app.py")

    if not os.path.exists(target_path) and getattr(sys, "frozen", False):
        bundled_path = os.path.join(sys._MEIPASS, "run_app.py")
        if os.path.exists(bundled_path):
            try:
                with open(bundled_path, "r", encoding="utf-8") as fsrc:
                    content = fsrc.read()
                with open(target_path, "w", encoding="utf-8") as fdst:
                    fdst.write(content)
            except Exception as e:
                log_error(data_dir, f"Không thể trích xuất run_app.py gốc từ bundle: {e}")

    try:
        res = requests.get(RUN_APP_URL, timeout=10)
        if res.status_code == 200 and res.text.strip():
            with open(target_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(res.text)
    except Exception as e:
        # Không có mạng hoặc tải lỗi: giữ nguyên bản run_app.py đang có sẵn (nếu có)
        log_error(data_dir, f"Không tải được run_app.py mới nhất, dùng bản hiện có (nếu có): {e}")

    return target_path


def bootstrap():
    data_dir = get_data_dir()
    run_app_path = ensure_local_run_app(data_dir)

    if not os.path.exists(run_app_path):
        log_error(data_dir, "Không tìm thấy run_app.py sau bootstrap (cả bundle lẫn tải mạng đều thất bại).")
        return

    try:
        with open(run_app_path, "r", encoding="utf-8") as f:
            code = f.read()
        # Truyền sẵn thư mục dữ liệu (đã tính ở trên) cho run_app.py qua biến toàn
        # cục LAUNCHER_DATA_DIR, để run_app.py không cần tự đoán lại và luôn dùng
        # đúng thư mục có thể ghi được này làm BASE_DIR.
        exec_globals = {
            "__name__": "__main__",
            "__file__": run_app_path,
            "LAUNCHER_DATA_DIR": data_dir,
        }
        exec(compile(code, run_app_path, "exec"), exec_globals)
    except Exception:
        log_error(data_dir, "Lỗi khi chạy run_app.py:\n" + traceback.format_exc())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    bootstrap()

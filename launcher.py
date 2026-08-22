import sys
import os
import requests
import multiprocessing

def bootstrap():
    # URL tải lõi vận hành từ GitHub của bạn (dùng jsdelivr để cập nhật tức thì)
    RUN_APP_URL = "https://cdn.jsdelivr.net/gh/thienphankh28-art/tdm-aminoglycosid-win@main/run_app.py"
    
    try:
        res = requests.get(RUN_APP_URL, timeout=10)
        if res.status_code == 200:
            # Ghi đè file run_app.py với chuẩn xuống dòng Windows
            with open("run_app.py", "w", encoding="utf-8", newline="") as f:
                f.write("\n".join(res.text.splitlines()) + "\n")
    except Exception:
        pass  # Nếu không có mạng, bỏ qua và chạy bản run_app.py lưu sẵn trên máy
        
    if os.path.exists("run_app.py"):
        with open("run_app.py", "r", encoding="utf-8") as f:
            code = f.read()
        exec(code, {'__name__': '__main__', '__file__': 'run_app.py'})
    else:
        print("Lỗi: Không tìm thấy file run_app.py.")

if __name__ == '__main__':
    multiprocessing.freeze_support()
    bootstrap()

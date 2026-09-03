import os
import sys
import shutil
import json
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import messagebox
import runpy

# ===== QUAN TRỌNG: SỬA ĐƯỜNG DẪN GITHUB CỦA BẠN VÀO ĐÂY =====
GITHUB_REPO_URL = "https://raw.githubusercontent.com/thienphankh28-art/tdm-aminoglycosid-win/main" 

FILES_TO_UPDATE = [
    "app.py",
    "database.py",
    "run_app.py",
    "pk_calculations.py",
    "vanco_calculations.py",
    "version.json"
]

def get_base_dir():
    """Lấy thư mục chứa file .exe hiện tại. 
    Lưu ý: Nếu bạn để exe trong thư mục cần cấp quyền Admin (như Program Files), việc tải file có thể bị từ chối."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_bundled_dir():
    """Lấy thư mục tạm chứa các file được Pyinstaller đính kèm bên trong file .exe (thư mục _MEI)"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def ask_continue_with_bundled(error_type, error_details):
    """Hiển thị popup hỏi người dùng có muốn chạy bản dự phòng trong exe khi có lỗi không"""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    
    if error_type == "network":
        title = "Lỗi kết nối mạng"
        msg = f"Không thể kiểm tra bản cập nhật trên GitHub.\nChi tiết: {error_details}\n\nBạn có muốn khởi chạy phần mềm bằng phiên bản mặc định có sẵn không?"
    elif error_type == "download":
        title = "Lỗi tải file"
        msg = f"Quá trình tải bản cập nhật bị lỗi.\nChi tiết: {error_details}\n\nBạn có muốn khởi chạy phần mềm bằng phiên bản mặc định có sẵn không?"
    elif error_type == "permission":
        title = "Lỗi quyền truy cập"
        msg = f"Không thể lưu file cập nhật vào thư mục hiện tại.\n(Có thể thư mục hoặc file đang bị hệ thống khóa)\nChi tiết: {error_details}\n\nBạn có muốn khởi chạy phần mềm bằng phiên bản mặc định có sẵn không?"
    else:
        title = "Lỗi cập nhật"
        msg = f"Đã xảy ra lỗi không xác định.\nChi tiết: {error_details}\n\nBạn có muốn khởi chạy phần mềm bằng phiên bản mặc định có sẵn không?"
        
    # Ask Yes/No
    choice = messagebox.askyesno(title, msg, parent=root)
    root.destroy()
    return choice

def extract_bundled_files(dest_dir):
    """Trích xuất file từ file .exe ra thư mục chứa exe nếu bên ngoài chưa có file nào"""
    bundled_dir = get_bundled_dir()
    for f in FILES_TO_UPDATE:
        src = os.path.join(bundled_dir, f)
        dst = os.path.join(dest_dir, f)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass

def check_and_update(dest_dir):
    """Kiểm tra và tải bản cập nhật từ Github"""
    local_version_file = os.path.join(dest_dir, "version.json")
    local_version = "V.0.0.0"
    
    # 1. Đọc số phiên bản hiện tại trên máy
    if os.path.exists(local_version_file):
        try:
            with open(local_version_file, "r", encoding="utf-8") as f:
                v_data = json.load(f)
                local_version = v_data.get("version", local_version)
        except Exception:
            pass

    remote_version_url = f"{GITHUB_REPO_URL}/version.json"
    
    # 2. Kiểm tra số phiên bản trên GitHub
    try:
        req = urllib.request.Request(remote_version_url, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=10) as response:
            remote_data = json.loads(response.read().decode('utf-8'))
            remote_version = remote_data.get("version", local_version)
            
    except urllib.error.URLError as e:
        return ask_continue_with_bundled("network", str(e.reason))
    except Exception as e:
        return ask_continue_with_bundled("network", str(e))
        
    # 3. Tiến hành tải nếu GitHub có bản mới hơn
    if remote_version != local_version:
        for f in FILES_TO_UPDATE:
            file_url = f"{GITHUB_REPO_URL}/{f}"
            file_dest = os.path.join(dest_dir, f)
            try:
                req_file = urllib.request.Request(file_url, headers={'Cache-Control': 'no-cache'})
                with urllib.request.urlopen(req_file, timeout=15) as response:
                    content = response.read()
                    with open(file_dest, "wb") as out_file:
                        out_file.write(content)
            except PermissionError as e:
                # Bắt lỗi không có quyền ghi đè (Permission Denied)
                return ask_continue_with_bundled("permission", str(e))
            except Exception as e:
                return ask_continue_with_bundled("download", f"Không thể tải file {f}: {str(e)}")
                
    return True # Trả về True nếu không có bản mới HOẶC cập nhật thành công

def run_bundled_app():
    """Khởi chạy ứng dụng từ bản nén bên trong .exe (Dùng khi cập nhật lỗi)"""
    bundled_dir = get_bundled_dir()
    sys.path.insert(0, bundled_dir)
    os.environ["TDM_APP_DATA_DIR"] = bundled_dir
    os.chdir(bundled_dir)
    try:
        runpy.run_module('run_app', run_name='__main__')
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("Lỗi khởi chạy", f"Không thể chạy ứng dụng bản dự phòng:\n{str(e)}", parent=root)
        root.destroy()
        sys.exit(1)

def run_local_app(dest_dir):
    """Khởi chạy ứng dụng bằng các file nằm ở thư mục ngoài (đã cập nhật)"""
    sys.path.insert(0, dest_dir)
    os.environ["TDM_APP_DATA_DIR"] = dest_dir
    os.chdir(dest_dir)
    try:
        runpy.run_module('run_app', run_name='__main__')
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("Lỗi khởi chạy", f"Không thể chạy ứng dụng từ thư mục hiện tại:\n{str(e)}", parent=root)
        root.destroy()
        sys.exit(1)

def main():
    # dest_dir lúc này là thư mục đang chứa file TDM_Aminoglycosid.exe
    dest_dir = get_base_dir()
    
    # 1. Trích xuất file đính kèm ra ngoài nếu đây là lần chạy đầu tiên
    extract_bundled_files(dest_dir)
    
    # 2. Kiểm tra/Tải bản cập nhật mới
    success = check_and_update(dest_dir)
    
    if success:
        # Nếu success = True (Tải thành công HOẶC phiên bản bằng nhau) -> Chạy file ở thư mục ngoài
        run_local_app(dest_dir)
    else:
        # Nếu success = False (Người dùng nhấn YES ở hộp thoại lỗi) -> Chạy bản dự phòng trong exe
        run_bundled_app()
        # Lưu ý: Nếu người dùng nhấn NO ở hộp thoại lỗi, ask_continue_with_bundled sẽ trả về False
        # Do đó code nhảy vào nhánh `else:` này, nhưng nếu bạn muốn thoát luôn khi nhấn NO thì sửa lại một chút ở logic trả về.
        # Ở đây tôi mặc định nếu False thì vẫn cố chạy bản bundled. Nếu muốn khắt khe hơn có thể chỉnh sửa hàm if.

if __name__ == "__main__":
    main()

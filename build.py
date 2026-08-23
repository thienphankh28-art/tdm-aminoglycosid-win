"""
build.py — Đóng gói phần mềm TDM Aminoglycosid thành file .exe bằng PyInstaller.

Lưu ý về luồng cập nhật (đã sửa lỗi "kiểm tra được nhưng không cập nhật được"):
launcher.py giờ lưu và cập nhật toàn bộ code (run_app.py, app.py, database.py,
pk_calculations.py, version.json) tại %LOCALAPPDATA%\\TDM_Aminoglycosid — một
thư mục LUÔN ghi được với user thường — thay vì thư mục cài đặt file .exe (có
thể bị Windows chặn ghi nếu đặt trong Program Files, thư mục do OneDrive quản
lý, v.v.). Vì vậy, danh sách --add-data dưới đây (nhúng bản gốc vào bên trong
.exe) vẫn cần đầy đủ 5 file như cũ, để launcher.py có thể trích xuất ra
%LOCALAPPDATA% cho LẦN CHẠY ĐẦU TIÊN kể cả khi máy KHÔNG có mạng.
"""

import PyInstaller.__main__

PyInstaller.__main__.run([
    'launcher.py',                  # File vỏ bọc cốt lõi
    '--onefile',
    '--noconsole',                  # Ẩn hoàn toàn cửa sổ CMD
                                     # (Khi cần debug lỗi khởi chạy, có thể tạm
                                     # comment dòng này để build bản có console,
                                     # hoặc xem log tại
                                     # %LOCALAPPDATA%\\TDM_Aminoglycosid\\update_log.txt
                                     # và \\launcher_error.log)
    '--name=TDM_Aminoglycosid',

    # Gom các thư viện cốt lõi (Đã bỏ streamlit, dùng customtkinter)
    '--collect-all=customtkinter',
    '--collect-all=supabase',
    '--collect-all=fpdf',

    # CustomTkinter cần Pillow để xử lý ảnh/bo góc; PyInstaller đôi khi không tự
    # phát hiện được submodule tích hợp Tkinter của Pillow nên khai báo tường minh
    # để tránh lỗi "ImportError: PIL._tkinter_finder" khi chạy bản .exe đã đóng gói.
    '--collect-all=PIL',
    '--hidden-import=PIL._tkinter_finder',

    # matplotlib dùng để vẽ biểu đồ nồng độ/xu hướng TDM (nhúng qua FigureCanvasTkAgg)
    '--collect-all=matplotlib',
    # numpy được pk_calculations.py dùng trực tiếp; collect-all để chắc chắn đủ
    # các submodule nhị phân cần thiết khi đóng gói --onefile
    '--collect-all=numpy',

    # Dự phòng thư viện cho tương lai
    '--collect-all=openpyxl',

    # Đính kèm toàn bộ mã nguồn lần đầu (được launcher.py trích xuất ra
    # %LOCALAPPDATA%\\TDM_Aminoglycosid ở lần chạy đầu tiên hoặc khi offline)
    '--add-data=run_app.py;.',
    '--add-data=app.py;.',
    '--add-data=database.py;.',
    '--add-data=pk_calculations.py;.',
    '--add-data=version.json;.',
])

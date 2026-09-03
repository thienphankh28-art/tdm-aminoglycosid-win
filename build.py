import PyInstaller.__main__

PyInstaller.__main__.run([
    'launcher.py',                  # File thực thi đầu tiên khi click .exe
    '--onefile',
    '--noconsole',                  # Ẩn cửa sổ cmd màu đen khi chạy
    '--name=TDM_Aminoglycosid',

    # Thư viện giao diện, database và pdf
    '--collect-all=customtkinter',
    '--collect-all=supabase',
    '--collect-all=fpdf',

    # Thư viện cho hình ảnh
    '--collect-all=PIL',
    '--hidden-import=PIL._tkinter_finder',

    # Các thư viện tính toán và báo cáo nội bộ (chứa trong code)
    '--collect-all=matplotlib',
    '--collect-all=numpy',
    '--collect-all=openpyxl',

    # ---- BƯỚC QUAN TRỌNG ----
    # Đóng gói ("nén") tất cả mã nguồn gốc này vào file .exe. 
    # Khi phần mềm khởi động, launcher.py sẽ "bung" các file này ra ngoài
    '--add-data=run_app.py;.',
    '--add-data=app.py;.',
    '--add-data=login_frame.py;.',
    '--add-data=tab1_aminoglycosid.py;.',
    '--add-data=tab2_patient_db.py;.',
    '--add-data=tab3_info.py;.',
    '--add-data=tab4_vancomycin.py;.',
    '--add-data=ui_common.py;.',
    '--add-data=database.py;.',
    '--add-data=vanco_calculations.py;.',
    '--add-data=pk_calculations.py;.',
    '--add-data=version.json;.',
    '--add-data=build.py;.',
])

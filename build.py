import PyInstaller.__main__

PyInstaller.__main__.run([
    'launcher.py',                  # File vỏ bọc cốt lõi
    '--onefile',
    '--noconsole',                  # Ẩn hoàn toàn cửa sổ CMD
    '--name=TDM_Aminoglycosid',
    
    # Gom các thư viện cốt lõi mới (Đã bỏ streamlit, thêm customtkinter)
    '--collect-all=customtkinter',
    '--collect-all=supabase',
    '--collect-all=fpdf',
    
    # Dự phòng thư viện cho tương lai
    '--collect-all=matplotlib',
    '--collect-all=openpyxl',
    
    # Đính kèm toàn bộ mã nguồn lần đầu
    '--add-data=run_app.py;.',
    '--add-data=app.py;.',
    '--add-data=database.py;.',
    '--add-data=pk_calculations.py;.',
    '--add-data=version.json;.',
])

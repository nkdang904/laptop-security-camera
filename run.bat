@echo off
title Camera An Ninh Laptop
chcp 65001 > nul
cd /d "%~dp0"
title Laptop Smart Security Camera
echo ========================================================
echo       KHOI DONG LAPTOP SMART SECURITY CAMERA
echo ========================================================
cd /d "%~dp0"

:: 1. Giai phong Webcam: Tat cac tien trinh camera cu neu bi treo
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" > nul 2>&1

:: 2. Tu dong tim duong dan Python chinh xac tren may
set "PY_CMD=python"
if exist "D:\laragon\bin\python\python-3.10\python.exe" (
    set "PY_CMD=D:\laragon\bin\python\python-3.10\python.exe"
)

echo ===================================================================
echo             HỆ THỐNG CAMERA AN NINH THÔNG MINH LAPTOP
echo             HE THONG CAMERA AN NINH THONG MINH LAPTOP
echo ===================================================================
echo.
echo  [*] Đang khởi động Webcam và kết nối Telegram Bot...
echo  [*] Để dừng camera: Bấm tổ hợp phím Ctrl + C (hoặc tắt cửa sổ này).
echo  [*] Dang khoi dong Webcam va ket noi Telegram Bot...
echo  [*] Trinh thuc thi: %PY_CMD%
echo  [*] Thu muc lam viec: %~dp0
echo  [*] Dang khoi dong Webcam, AI va Telegram Bot...
echo  [*] De dung camera: Bam to hop phim Ctrl + C (hoac tat cua so nay).
echo.
echo ===================================================================
echo.

python main.py
"%PY_CMD%" main.py

if errorlevel 1 (
    echo.
    echo [CANH BAO] Chuong trinh dung voi ma loi %errorlevel%.
)

echo.
echo [*] Camera đã dừng.
echo [*] Camera da dung hoat dong.
pause


@echo off
setlocal
cd /d "%~dp0"
title Laptop Smart Security Camera

set "PY=python"
if exist "D:\laragon\bin\python\python-3.10\python.exe" (
    set "PY=D:\laragon\bin\python\python-3.10\python.exe"
)

echo ===================================================================
echo             HE THONG CAMERA AN NINH THONG MINH LAPTOP
echo ===================================================================
echo  [*] Trinh thuc thi: %PY%
echo  [*] Thu muc: %~dp0
echo  [*] Dang khoi dong Webcam, AI, Live Stream va Telegram Bot...
echo  [*] De dung camera: Bam to hop phim Ctrl + C (hoac dong cua so)
echo ===================================================================
echo.

"%PY%" main.py

if errorlevel 1 (
    echo.
    echo [CANH BAO] Chuong trinh dung voi ma loi %errorlevel%.
)

echo.
echo [*] Camera da dung hoat dong.
pause

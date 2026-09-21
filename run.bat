@echo off
title Camera An Ninh Laptop
chcp 65001 > nul
title Laptop Smart Security Camera
echo ========================================================
echo       KHOI DONG LAPTOP SMART SECURITY CAMERA
echo ========================================================
cd /d "%~dp0"

echo ===================================================================
echo             HỆ THỐNG CAMERA AN NINH THÔNG MINH LAPTOP
echo ===================================================================
echo.
echo  [*] Đang khởi động Webcam và kết nối Telegram Bot...
echo  [*] Để dừng camera: Bấm tổ hợp phím Ctrl + C (hoặc tắt cửa sổ này).
echo.
echo ===================================================================
echo.

python main.py

echo.
echo [*] Camera đã dừng.
pause


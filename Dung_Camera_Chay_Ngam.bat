@echo off
title Dung Camera Chay Ngam
chcp 65001 > nul
echo Đang tìm và tắt tiến trình camera...
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host 'Đã tắt tiến trình PID:' $_.ProcessId }"
echo Dang tim va tat tien trinh camera...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host 'Da tat tien trinh PID:' $_.ProcessId }"
echo.
echo [x] Camera đã được dừng hoàn toàn!
timeout /t 3

echo [*] Da dung camera hoan toan.
timeout /t 3 > nul

@echo off
title Dung Camera Chay Ngam
echo Dang tim va tat tien trinh camera...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host 'Da tat tien trinh PID:' $_.ProcessId }"
echo.
echo [*] Da dung camera hoan toan.
timeout /t 3 > nul

# Script khoi dong Camera qua PowerShell
Set-Location -Path $PSScriptRoot

$py = "python"
if (Test-Path "D:\laragon\bin\python\python-3.10\python.exe") {
    $py = "D:\laragon\bin\python\python-3.10\python.exe"
}

Write-Host "===================================================================" -ForegroundColor Cyan
Write-Host "            HE THONG CAMERA AN NINH THONG MINH LAPTOP" -ForegroundColor Green
Write-Host "===================================================================" -ForegroundColor Cyan
Write-Host " [*] Python: $py"
Write-Host " [*] Dang khoi dong Webcam, AI, Live Stream va Telegram Bot..."
Write-Host " [*] Nhan Ctrl + C de dung camera."
Write-Host "===================================================================" -ForegroundColor Cyan

& $py main.py

Read-Host "Nhan Enter de thoat..."

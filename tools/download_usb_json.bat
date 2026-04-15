@echo off
setlocal

set PORT=%1
set OUTPUT=%2

if "%PORT%"=="" set PORT=COM7
if "%OUTPUT%"=="" set OUTPUT=snare_scan_data.json

powershell -ExecutionPolicy Bypass -File "%~dp0download_usb_json.ps1" -Port "%PORT%" -OutputPath "%OUTPUT%"

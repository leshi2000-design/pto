@echo off
chcp 65001 >nul
title ПТО Сервер — автозапуск
echo.
echo  1 - сервер с окном, запуск при входе в Windows (проще, пароль не нужен)
echo  2 - сервер без окна, запуск при включении компьютера (нужен пароль Windows)
echo.
set /p CH=Выберите 1 или 2: 
set MODE=Logon
if "%CH%"=="2" set MODE=Boot
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%~dp0Setup-PtoServerAutostart.ps1"" -Mode %MODE%'"

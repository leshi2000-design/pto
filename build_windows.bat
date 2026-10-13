@echo off
rem Сборка готовой программы для Windows: dist\СМЕТА-ГАЗ\SmetaGaz.exe (+ установщик, если установлен Inno Setup)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller || goto :fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean smetagaz.spec || goto :fail
where iscc >nul 2>nul && iscc packaging\installer.iss
echo.
echo Готово: dist\СМЕТА-ГАЗ\SmetaGaz.exe  (установщик, если собран: dist\SmetaGaz_Setup.exe)
pause
exit /b 0
:fail
echo Сборка не удалась.
pause
exit /b 1

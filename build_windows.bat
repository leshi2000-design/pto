@echo off
rem Сборка готовой программы для Windows: dist\ПТО\PTO.exe (+ установщик, если установлен Inno Setup)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller || goto :fail
.venv\Scripts\python.exe -c "import sys, PyQt6.QtCore as q; print('Python', sys.version.split()[0], '| PyQt6', q.PYQT_VERSION_STR)" || (echo PyQt6 не установился в .venv. Смотрите сообщения pip выше. Нужен Python 3.11 или 3.12 ^(64-bit^). & goto :fail)
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean smetagaz.spec || goto :fail
del /q "dist\ПТО\selftest.txt" 2>nul
start /wait "" "dist\ПТО\PTO_Server.exe" --selftest
if exist "dist\ПТО\selftest.txt" (type "dist\ПТО\selftest.txt") else (echo Самопроверка ПТО Сервера не отработала: dist\ПТО\PTO_Server.exe не запускается & goto :fail)
findstr /c:"ЕСТЬ ОШИБКИ" "dist\ПТО\selftest.txt" >nul && goto :fail
where iscc >nul 2>nul && iscc packaging\installer.iss
echo.
echo Готово: dist\ПТО\PTO.exe  (установщик, если собран: dist\PTO_Setup.exe)
pause
exit /b 0
:fail
echo Сборка не удалась.
pause
exit /b 1

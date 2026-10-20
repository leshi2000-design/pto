@echo off
chcp 65001 >nul
rem Сборка одного файла HomeFinance.exe (нужен Python 3.11+ в PATH). Результат: dist\HomeFinance.exe
cd /d "%~dp0"
if not exist .venv-build (
  python -m venv .venv-build || (echo Установите Python 3.11+ с python.org & pause & exit /b 1)
)
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-homefin.txt pyinstaller || (echo Не удалось установить зависимости & pause & exit /b 1)
pyinstaller --noconfirm --clean --onefile --windowed --name HomeFinance ^
  --icon homefin\assets\icon.ico --add-data "homefin\assets;homefin\assets" ^
  --hidden-import PyQt6.QtSvg --hidden-import openpyxl ^
  run_homefin.py || (echo Сборка не удалась & pause & exit /b 1)
echo.
echo Готово: %~dp0dist\HomeFinance.exe
echo Данные программы хранятся в папке пользователя: %USERPROFILE%\.homefin
pause

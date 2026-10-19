@echo off
chcp 65001 >nul
rem Сборка программы для Windows: dist\ПТО\PTO.exe (+ установщик, если установлен Inno Setup).
rem   build_windows.bat          - только программа (без сервера)
rem   build_windows.bat server   - программа и ПТО Сервер
cd /d "%~dp0"
set PTO_WITH_SERVER=
if /i "%1"=="server" set PTO_WITH_SERVER=1
set PY=.venv\Scripts\python.exe
if not exist %PY% py -3 -m venv .venv
if not exist %PY% (echo Не удалось создать .venv: установите Python 3.11 или 3.12 ^(64-bit^) с python.org и отметьте Add python.exe to PATH. & goto :fail)
for %%F in (requirements.txt) do if %%~zF LSS 50 (echo Файл requirements.txt пуст или повреждён. Распакуйте архив заново. & goto :fail)
%PY% -m pip install -r requirements.txt pyinstaller || goto :fail
%PY% -c "import PyQt6.QtCore" 2>nul || (
  echo PyQt6 не найден после установки. Переустанавливаю...
  %PY% -m pip install --force-reinstall --no-cache-dir PyQt6 PyQt6-Qt6 PyQt6-sip || goto :fail
)
%PY% -c "import sys, PyQt6.QtCore as q; print('Python', sys.version.split()[0], '| PyQt6', q.PYQT_VERSION_STR)" || (
  echo.
  echo === ДИАГНОСТИКА ===
  %PY% --version
  %PY% -m pip list
  echo Путь сборки: %CD% ^(лучше короткий, например C:\PTO^)
  goto :fail
)
%PY% -m PyInstaller --noconfirm --clean smetagaz.spec || goto :fail
del /q "dist\ПТО\selftest.txt" 2>nul
start /wait "" "dist\ПТО\PTO.exe" --selftest
if exist "dist\ПТО\selftest.txt" (type "dist\ПТО\selftest.txt") else (echo Самопроверка не отработала: dist\ПТО\PTO.exe не запускается & goto :fail)
findstr /c:"ЕСТЬ ОШИБКИ" "dist\ПТО\selftest.txt" >nul && goto :fail
where iscc >nul 2>nul && iscc packaging\installer.iss
echo.
echo Готово: dist\ПТО\PTO.exe  (установщик, если собран: dist\PTO_Setup.exe)
pause
exit /b 0
:fail
echo.
echo Сборка не удалась. Смотрите сообщения выше и docs\BUILD_WINDOWS_RU.md
pause
exit /b 1

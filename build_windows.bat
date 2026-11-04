@echo off
chcp 65001 >nul
rem Сборка программы для Windows: dist\ПТО\PTO.exe (+ установщик, если установлен Inno Setup).
rem   build_windows.bat          - только программа (без сервера)
rem   build_windows.bat server   - программа и ПТО Сервер
cd /d "%~dp0"
set PTO_WITH_SERVER=
if /i "%1"=="server" set PTO_WITH_SERVER=1
set PY=.venv\Scripts\python.exe
rem Подходит только Python 3.10-3.13: для более новых нет готовых сборок pandas и др., и pip пытается собирать их из исходников (нужен Visual Studio) - сборка падает.
if exist %PY% %PY% -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" || (
  echo Окружение .venv создано неподходящей версией Python - пересоздаю.
  rmdir /s /q .venv
)
if not exist %PY% for %%V in (3.12 3.11 3.13 3.10) do if not exist %PY% py -%%V -m venv .venv 2>nul
if not exist %PY% (
  echo Не найден Python 3.10-3.13 ^(рекомендуется 3.12, 64-bit^). Более новые версии ^(3.14 и выше^) для сборки не подходят.
  echo Установите Python 3.12 с python.org ^(отметьте Add python.exe to PATH^) или командой: winget install Python.Python.3.12
  echo Установленные версии Python:
  py -0p
  goto :fail
)
for %%F in (requirements.txt) do if %%~zF LSS 50 (echo Файл requirements.txt пуст или повреждён. Распакуйте архив заново. & goto :fail)
%PY% -m pip install --upgrade pip >nul 2>&1
%PY% -m pip install --only-binary=:all: -r requirements.txt pyinstaller || (
  echo.
  echo Не удалось установить библиотеки готовыми пакетами. Обычно это значит, что Python слишком новый или 32-разрядный: нужен Python 3.12 ^(64-bit^).
  echo Удалите папку .venv и запустите build_windows.bat снова.
  goto :fail
)
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

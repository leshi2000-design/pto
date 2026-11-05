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
if not exist %PY% if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
if exist %PY% goto :have_python
echo.
echo Не найден Python 3.10-3.13 (нужен 64-bit, рекомендуется 3.12). Более новые версии (3.14 и выше) для сборки не подходят: для них нет готовых пакетов pandas и др.
echo Установленные версии Python:
py -0p
echo.
echo Можно скачать и установить Python 3.12 автоматически: только для вашего пользователя, без прав администратора, ~25 МБ, нужен интернет.
echo Уже установленный Python 3.14 остаётся, ничего не ломается.
set ANS=
set /p ANS=Установить Python 3.12 сейчас? [Y/N]: 
if /i not "%ANS%"=="Y" goto :python_manual
set PYSETUP=%TEMP%\python-3.12.10-amd64.exe
echo Скачиваю Python 3.12.10 с python.org ...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe -OutFile $env:TEMP\python-3.12.10-amd64.exe" || goto :python_manual
echo Устанавливаю Python 3.12 (окно установки покажет ход; если Windows спросит разрешение - нажмите Да)...
"%PYSETUP%" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 || goto :python_manual
del /q "%PYSETUP%" 2>nul
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
if exist %PY% goto :have_python
:python_manual
echo.
echo Установите Python 3.12 вручную: https://www.python.org/downloads/windows/ (Windows installer 64-bit, версия 3.12.x), отметьте Add python.exe to PATH,
echo затем запустите build_windows.bat снова. Подробности: docs\BUILD_WINDOWS_RU.md
goto :fail
:have_python
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

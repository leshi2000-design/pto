@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements-tested.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe run_shop.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Failed to install or start Magazin. See the error above.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"
set PYW=%~dp0backend\.venv\Scripts\pythonw.exe
set PY=%~dp0backend\.venv\Scripts\python.exe
if exist "%PYW%" (
  start "" "%PYW%" "%~dp0scripts\chipsutra_local_app.py"
  exit /b 0
)
if exist "%PY%" (
  start "" "%PY%" "%~dp0scripts\chipsutra_local_app.py"
  exit /b 0
)
echo Missing backend\.venv — creating it is a one-time step.
echo Run in PowerShell:
echo   cd /d "%~dp0backend"
echo   py -3.12 -m venv .venv
echo   .\.venv\Scripts\python.exe -m pip install -r requirements-oss.txt
echo Then double-click this file again.
pause

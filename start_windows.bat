@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe goto dependencies
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.12 from python.org, then run this file again.
  pause
  exit /b 1
)
py -3.12 -m venv .venv
if errorlevel 1 goto failed
:dependencies
.venv\Scripts\python.exe -c "import numpy, pandas, sklearn, matplotlib, scipy" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe main.py --offline
if errorlevel 1 goto failed
exit /b 0
:failed
echo Launch failed. See the message above and README.md.
pause
exit /b 1

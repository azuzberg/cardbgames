@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.13 -c "import sys; assert sys.version_info[:3] == (3,13,3), 'Install Python 3.13.3 first.'"
  if errorlevel 1 exit /b 1
  py -3.13 -m venv .venv
  if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -c "import sys; assert sys.version_info[:3] == (3,13,3), 'Recreate .venv using Python 3.13.3.'"
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe app.py

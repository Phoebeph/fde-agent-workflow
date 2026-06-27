@echo off
setlocal

cd /d "%~dp0\.."

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python"
)

call "%PYTHON_EXE%" scripts\check_config.py --mode backend
if errorlevel 1 exit /b 1

call "%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

@echo off
setlocal

cd /d "%~dp0\.."

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python"
)

call "%PYTHON_EXE%" scripts\check_config.py --mode yingdao
if errorlevel 1 exit /b 1

if "%YINGDAO_ENTRY_COMMAND%"=="" (
  echo YINGDAO_ENTRY_COMMAND is empty. Configure it in .env before scheduling this script.
  exit /b 1
)

call %YINGDAO_ENTRY_COMMAND%

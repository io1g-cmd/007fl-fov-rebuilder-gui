@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
py -3 --version >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD python --version >nul 2>nul && set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    echo Python 3 was not found.
    pause
    exit /b 1
)

%PYTHON_CMD% -m pip install -r requirements.txt -q
%PYTHON_CMD% fov_rebuilder_gui.py
exit /b %ERRORLEVEL%

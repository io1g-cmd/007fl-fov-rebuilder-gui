@echo off
setlocal EnableExtensions
cd /d "%~dp0"

call :find_python
if errorlevel 1 call :install_python
if errorlevel 1 goto :fail_python

call :find_python
if errorlevel 1 goto :fail_python

echo Installing Python dependency (lz4) if needed...
%PYTHON_CMD% -m pip install -r requirements.txt -q
if errorlevel 1 %PYTHON_CMD% -m pip install lz4 -q

%PYTHON_CMD% fov_rebuilder_gui.py
exit /b %ERRORLEVEL%

:find_python
set "PYTHON_CMD="
py -3 --version >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD python --version >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON_CMD if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python311\python.exe"
if defined PYTHON_CMD exit /b 0
exit /b 1

:install_python
echo Python 3 not found. Trying winget install...
where winget >nul 2>nul || exit /b 1
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
exit /b 0

:fail_python
echo.
echo Python 3 is required. Install from https://www.python.org/downloads/
echo Then run Launch.bat again.
pause
exit /b 1

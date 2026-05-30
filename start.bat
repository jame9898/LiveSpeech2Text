@echo off
cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ not found in PATH
    echo Please install Python 3.10+ first: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.dirname(sys.executable))"') do set "PYDIR=%%i"

if not exist "%PYDIR%\pythonw.exe" (
    echo [WARN] pythonw.exe not found, using python.exe instead
    start "" python app.py
) else (
    start "" "%PYDIR%\pythonw.exe" app.py
)
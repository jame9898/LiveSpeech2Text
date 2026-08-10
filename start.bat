@echo off
rem Usage: double-click (shows a brief console window) or run via 启动.vbs (fully windowless)
rem The `h` argument is used by 启动.vbs to launch the real body.
if "%~1"=="h" goto :run
start "" wscript.exe "%~dp0启动.vbs"
exit /b

:run
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

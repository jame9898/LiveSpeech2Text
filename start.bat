@echo off
cd /d "%~dp0"

REM 优先使用虚拟环境（若存在），否则用系统 Python
set "PYEXE="
set "PYWEXE="

if exist "%~dp0venv\Scripts\python.exe" (
    set "PYEXE=%~dp0venv\Scripts\python.exe"
    set "PYWEXE=%~dp0venv\Scripts\pythonw.exe"
) else (
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] 未找到 Python 3.10+
        echo 请先安装 Python 3.10+ : https://www.python.org/downloads/
        pause
        exit /b 1
    )
    for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)"') do set "PYEXE=%%i"
    for %%f in ("%PYEXE%") do set "PYWEXE=%%~dpfpythonw.exe"
)

REM 快速依赖检查（避免依赖缺失时静默退出）
"%PYEXE%" -c "import torch, qwen_asr, PySide6" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] 检测到依赖缺失，请先安装依赖：
    echo   venv 环境: venv\Scripts\activate ^&^& pip install -r requirements.txt
    echo   系统 环境: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM 优先用 pythonw 无窗口启动，找不到则用 python
if exist "%PYWEXE%" (
    start "" "%PYWEXE%" app.py
) else (
    start "" "%PYEXE%" app.py
)

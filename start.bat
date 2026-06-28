@echo off
cd /d "%~dp0"

REM HF 版必须使用项目内 venv 的 Python（含源码版 transformers，支持 qwen3_asr 架构）
set "PY=%~dp0venv\Scripts\python.exe"
set "PYW=%~dp0venv\Scripts\pythonw.exe"

if not exist "%PY%" (
    echo [ERROR] venv not found: %PY%
    echo Please create venv first:  python -m venv venv
    echo Then install deps:         venv\Scripts\pip install -r requirements-gpu.txt
    pause
    exit /b 1
)

if not exist "%PYW%" (
    echo [WARN] pythonw.exe not found, using python.exe instead
    start "" "%PY%" app.py
) else (
    start "" "%PYW%" app.py
)

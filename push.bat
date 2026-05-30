@echo off
cd /d "%~dp0"
echo ============================================================
echo   Push to GitHub
echo ============================================================
echo.

set /p MSG="Commit message: "

if "%MSG%"=="" (
    echo [ERROR] Commit message cannot be empty.
    pause
    exit /b 1
)

echo.
echo git add -A ...
git add -A

echo git commit -m "%MSG%" ...
git commit -m "%MSG%"

echo git push ...
git push

if %errorlevel% neq 0 (
    echo.
    echo [FAIL] Push failed. Check your remote URL:
    echo   git remote -v
    pause
    exit /b 1
)

echo.
echo [OK] Pushed successfully!
pause
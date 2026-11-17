@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 -m civa demo
) else (
    python -m civa demo
)
echo.
echo Open runs\demo\full_report.html in your browser.
pause

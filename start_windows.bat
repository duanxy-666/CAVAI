@echo off
setlocal
cd /d "%~dp0"
rem Prefer the existing venv next to CAVAI_v0.2, as in the user's PyCharm layout.
set "PYEXE=python"
if exist "..\\venv\\Scripts\\python.exe" set "PYEXE=..\\venv\\Scripts\\python.exe"
if exist ".venv\\Scripts\\python.exe" set "PYEXE=.venv\\Scripts\\python.exe"
echo [CAVAI] Python: %PYEXE%
"%PYEXE%" -m pip install -r requirements.txt
if errorlevel 1 goto error
echo.
echo [CAVAI] Start CATIA V5, then open http://127.0.0.1:8000
"%PYEXE%" run.py
pause
exit /b 0
:error
echo [CAVAI] Missing dependency or incompatible Python.
pause
exit /b 1

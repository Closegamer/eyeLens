@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating eyeLens virtual environment...
    py -3.12 -m venv .venv
    if errorlevel 1 goto :setup_error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :setup_error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :setup_error
)

".venv\Scripts\python.exe" -m eyelens %*
exit /b %errorlevel%

:setup_error
echo.
echo eyeLens setup failed. Make sure Python 3.12 is installed and you are online.
pause
exit /b 1

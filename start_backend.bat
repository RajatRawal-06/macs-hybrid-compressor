@echo off
REM ════════════════════════════════════════════════════════════════
REM  start_backend.bat — One-click Flask backend launcher
REM  Usage: double-click OR run from repo root
REM ════════════════════════════════════════════════════════════════
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║       MACS Compressor Backend v1.0       ║
echo  ║   Hybrid Residual Compression Engine     ║
echo  ╚══════════════════════════════════════════╝
echo.

cd /d "%~dp0backend"

REM Check for virtual environment
if exist "venv\Scripts\activate.bat" (
    echo [*] Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo [!] No venv found. Creating one...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo [*] Installing dependencies...
    pip install -r requirements.txt
)

REM Check if Flask is installed
python -c "import flask" 2>nul
if errorlevel 1 (
    echo [!] Flask not found. Installing dependencies...
    pip install -r requirements.txt
)

REM Generate sample files if missing
if not exist "..\samples\sample.jpg" (
    echo [*] Generating sample files...
    cd ..
    python generate_samples.py
    cd backend
)

echo.
echo [*] Starting Flask server on http://localhost:5000
echo [*] Press Ctrl+C to stop
echo.
python app.py

pause

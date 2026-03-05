@echo off
echo ============================================
echo  SimpleProxy - Build Script
echo ============================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH. Please install Python and try again.
    pause
    exit /b 1
)

:: Install / upgrade dependencies
echo [1/3] Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

:: Generate icon if missing
if not exist icon.ico (
    echo [1.5/3] Generating icon.ico...
    python make_icon.py
)

:: Build with PyInstaller
echo [2/3] Building executable...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name SimpleProxy ^
    --icon icon.ico ^
    --add-data "config.json;." ^
    proxy.py

if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

:: Copy config next to exe so user can edit it
echo [3/3] Copying config to dist folder...
copy /Y config.json dist\config.json >nul

echo.
echo ============================================
echo  Build complete!
echo  Your executable is in: dist\SimpleProxy.exe
echo  Edit dist\config.json to configure.
echo ============================================
echo.
pause

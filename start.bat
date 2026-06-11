@echo off
echo ========================================
echo   File Sharing Bot - Starting...
echo ========================================
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo ERROR: Python not found!
    echo Install from https://python.org - tick "Add to PATH"
    pause
    exit /b
)
pip install python-telegram-bot --upgrade -q
echo.
python bot.py
pause

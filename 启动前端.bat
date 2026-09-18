@echo off
cd /d "%~dp0"
echo ============================================
echo  FlawScope frontend starting...
echo  Browser opens automatically when ready.
echo  Manual URL: http://localhost:8501
echo ============================================
"%~dp0venv\Scripts\python.exe" "%~dp0run_app.py"
echo.
echo Frontend stopped.
pause

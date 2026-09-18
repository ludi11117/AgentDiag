@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  FlawScope Streamlit 前端（历史页 / 统计页）
echo  端口 8501
echo ============================================
"%~dp0venv\Scripts\python.exe" "%~dp0run_app.py"
echo.
echo 前端已停止。
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  FlawScope 后端 API
echo  端口 8000
echo  浏览器访问 http://localhost:8000/docs 可看接口文档
echo ============================================
"%~dp0venv\Scripts\python.exe" -m uvicorn api:app --host 127.0.0.1 --port 8000
echo.
echo 后端已停止。
pause

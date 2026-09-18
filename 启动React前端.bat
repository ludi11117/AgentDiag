@echo off
chcp 65001 >nul
cd /d "%~dp0web"
echo ============================================
echo  FlawScope React 前端
echo  http://localhost:5173
echo  需先启动后端（启动后端.bat）
echo ============================================
if not exist node_modules (
    echo 首次运行，正在安装依赖...
    call npm install
)
call npm run dev
echo.
echo 前端已停止。
pause

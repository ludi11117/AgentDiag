@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   FlawScope 一键启动（后端 + React 前端）
echo ------------------------------------------------------------
echo   后端 API   http://127.0.0.1:8000   （接口文档 /docs）
echo   前端页面   http://127.0.0.1:5173
echo ------------------------------------------------------------
echo   关闭本窗口即同时停止两个服务。
echo ============================================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [错误] 找不到 venv\Scripts\python.exe
    echo        请先在项目目录执行：python -m venv venv
    pause
    exit /b 1
)

if not exist "web\node_modules" (
    echo [提示] 前端依赖未安装，首次启动需要几分钟...
    pushd web
    call npm install
    popd
)

echo [1/2] 启动后端 API（端口 8000）...
start "FlawScope 后端" cmd /k ""%~dp0venv\Scripts\python.exe" -m uvicorn api:app --host 127.0.0.1 --port 8000"

echo [2/2] 启动 React 前端（端口 5173）...
start "FlawScope 前端" cmd /k "cd /d "%~dp0web" && npm run dev"

echo.
echo 两个服务已在独立窗口启动：
echo   - FlawScope 后端   （关闭它 = 停止 API）
echo   - FlawScope 前端   （关闭它 = 停止页面）
echo.
echo 后端初始化需要十几秒（加载向量库），稍等片刻再访问：
echo   http://127.0.0.1:5173
echo.
pause

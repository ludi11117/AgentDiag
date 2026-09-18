#!/bin/sh
set -e

echo "[FlawScope] 启动 FastAPI (端口 8000)..."
uvicorn api:app --host 0.0.0.0 --port 8000 &
API_PID=$!

echo "[FlawScope] 启动 Streamlit (端口 8501)..."
streamlit run app.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true &
WEB_PID=$!

trap "echo '[FlawScope] 收到退出信号，关闭服务...'; kill $API_PID $WEB_PID 2>/dev/null || true" TERM INT

wait
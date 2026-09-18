"""FlawScope 前端启动器：启动 Streamlit 并在服务就绪后自动打开浏览器。

用法：
    venv\\Scripts\\python.exe run_app.py
"""

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8501
# 固定用 127.0.0.1：避免 localhost 被解析到 IPv6 ::1 或走系统代理，
# 导致浏览器 WebSocket 连接迟迟连不上（表现为“打开很慢”）。
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"


def _is_ready() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def _warm_up():
    """先请求一次首页，让前端资源在服务端就绪，减少浏览器等待。"""
    try:
        with urllib.request.urlopen(URL, timeout=5) as resp:
            resp.read(1)
    except Exception:
        pass


def _open_browser_when_ready(timeout: int = 180):
    """轮询端口，服务真正就绪后再打开浏览器（避免固定延时导致打开空白页）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_ready():
            _warm_up()
            _open_browser()
            return
        time.sleep(0.3)


def _open_browser():
    try:
        if sys.platform.startswith("win"):
            # os.startfile 立刻返回，不会阻塞等待浏览器进程
            os.startfile(URL)  # noqa: S606
        else:
            import webbrowser
            webbrowser.open(URL)
    except Exception:
        pass


def main():
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    cmd = [
        sys.executable, "-m", "streamlit", "run", os.path.join(HERE, "app.py"),
        "--server.address=0.0.0.0",
        f"--server.port={PORT}",
        "--server.headless=true",
        # 关闭文件监听：Windows 下大幅减少启动/运行开销
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
        # 让前端也用 127.0.0.1 连接，避开 localhost/IPv6/代理问题
        f"--browser.serverAddress={HOST}",
    ]
    try:
        subprocess.run(cmd, cwd=HERE)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

@echo off
echo ============================================
echo  FlawScope 公网访问启动
echo  前提：前端(启动前端.bat)已经先运行
echo  等约 10 秒后，在本窗口找这一行：
echo    https://xxx.trycloudflare.com
echo  把那个网址发给任何人，就能访问你的系统
echo  （此窗口不能关，关了链接就断；电脑关机也失效）
echo ============================================
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8501 --no-autoupdate
echo.
echo 隧道已断开。
pause
"""早期原型脚本（历史参考，不再维护）。

正式入口见根目录：orchestrator.py（状态机）/ app.py（前端）/ api.py（接口）。
这些脚本依赖根目录的 .env 与 chroma_db/，请从项目根目录运行，例如：
    python legacy/search_test.py
"""
import requests

url = "http://127.0.0.1:8000/diagnose"

payload = {
    "fault_description": "设备类型：数控机床主轴电机\n报警代码：E-203\n现象：主轴转速不稳定，异响，温升异常"
}

try:
    response = requests.post(url, json=payload, timeout=120)
    print("状态码：", response.status_code)
    print("返回内容：")
    print(response.text)
except Exception as e:
    print("请求失败：", e)
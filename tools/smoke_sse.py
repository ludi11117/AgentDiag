"""SSE 端点的端到端冒烟验证（不调真实 LLM）。

为什么要单独写这个脚本而不只依赖 pytest：
    TestClient 走的是 ASGI 内部调用，**不经过网络栈**——它看不出
    分块传输、缓冲头、真实 TCP 分片这些只在真 HTTP 连接上才会暴露的问题。
    而 SSE 恰恰是最依赖这些的一类接口。所以这里用真实 HTTP 请求复核一遍。

用法：
    1. 另开终端启动后端：venv/Scripts/python.exe -m uvicorn api:app --port 8000
    2. 运行本脚本：venv/Scripts/python.exe tools/smoke_sse.py

注意：本脚本会真实发起诊断（除非后端已桩掉模型），耗时约 30~90 秒、
消耗一次 LLM 配额。仅用于最终验收，不要放进 CI。
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
FAULT = "那台数控机床主轴转起来一顿一顿的，还有怪声，温度也高得离谱"


def check_health() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/health/live", timeout=5) as resp:
            body = json.loads(resp.read())
            print(f"  /health/live -> {resp.status} {body}")
            return True
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  /health/live 失败：{e}")
        return False


def stream_diagnosis() -> int:
    """发起 SSE 请求，逐条打印事件到达的时间差。

    时间差是关键证据：如果所有事件在同一毫秒到达，说明被缓冲了，SSE 没生效。
    """
    payload = json.dumps({"fault_description": FAULT}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/diagnose/stream",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    print("  发起 POST /diagnose/stream ...")
    started = time.perf_counter()
    event_count = 0
    first_event_at = None
    arrival_times = []

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            print(f"  HTTP {resp.status}  content-type={resp.headers.get('content-type')}")
            print(f"  x-accel-buffering={resp.headers.get('x-accel-buffering')}")

            buffer = ""
            for raw in resp:
                buffer += raw.decode("utf-8")
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    block = block.strip()
                    if not block:
                        continue
                    event_count += 1
                    elapsed = time.perf_counter() - started
                    arrival_times.append(elapsed)
                    if first_event_at is None:
                        first_event_at = elapsed

                    name, data = "", ""
                    for line in block.split("\n"):
                        if line.startswith("event:"):
                            name = line[6:].strip()
                        elif line.startswith("data:"):
                            data = line[5:].strip()

                    if name == "progress":
                        d = json.loads(data)
                        print(f"  [{elapsed:6.2f}s] progress  {d.get('label', '')[:44]}")
                    elif name == "result":
                        d = json.loads(data)
                        print(f"  [{elapsed:6.2f}s] result    status={d.get('status')} "
                              f"record_id={d.get('record_id')} "
                              f"工单={'有' if d.get('workorder') else '无'}")
                    elif name == "done":
                        print(f"  [{elapsed:6.2f}s] done")
                    elif name == "error":
                        d = json.loads(data)
                        print(f"  [{elapsed:6.2f}s] error     {d.get('detail')}")

    except urllib.error.HTTPError as e:
        print(f"  HTTP 错误 {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
        return 1
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  连接失败：{e}")
        return 1

    print()
    print(f"  共收到 {event_count} 个事件，总耗时 {time.perf_counter() - started:.2f}s")

    if event_count == 0:
        print("  ✗ 未收到任何事件")
        return 1

    # 判定 1：事件必须分散到达，而不是攒到最后一起出来
    span = arrival_times[-1] - first_event_at
    print(f"  首末事件时间跨度：{span:.2f}s")
    if span < 0.05 and event_count > 2:
        print("  ✗ 所有事件几乎同时到达 —— 响应被缓冲了，SSE 未生效")
        return 1
    print("  ✓ 事件分批到达，流式生效")

    return 0


def main() -> int:
    print("=== SSE 端到端冒烟验证 ===")
    print()
    print("[1/2] 存活检查")
    if not check_health():
        print("\n后端未启动。请先执行：")
        print("  venv/Scripts/python.exe -m uvicorn api:app --port 8000")
        return 1

    print()
    print("[2/2] 流式诊断")
    rc = stream_diagnosis()
    print()
    print("=== 结果：" + ("通过" if rc == 0 else "失败") + " ===")
    return rc


if __name__ == "__main__":
    sys.exit(main())

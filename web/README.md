# FlawScope 前端

React 18 + TypeScript + Vite。从"Streamlit 直连业务模块"改为真正的前后端分离：
前端只经 HTTP 调用 FastAPI，`api.py` 从"被绕过的摆设"变成唯一入口。

## 快速开始

```bash
# 终端 1：后端
cd ..
venv/Scripts/python.exe -m uvicorn api:app --port 8000

# 终端 2：前端
cd web
npm install
npm run dev          # http://localhost:5173
```

Vite 会把 `/api/*` 代理到 `http://127.0.0.1:8000`，因此**不需要**在后端配 CORS 也能开发。
前端代码里所有请求都写 `/api` 前缀，不出现后端主机名——开发期由 Vite 代理，
生产期由 nginx 反代承担同样的角色（见 `nginx.conf`）。

若后端不在默认端口，用 `VITE_API_PROXY_TARGET=http://127.0.0.1:9000 npm run dev` 覆盖。

## 命令

| 命令 | 说明 |
|---|---|
| `npm run dev` | 开发服务器（5173） |
| `npm run build` | 类型检查 + 生产构建 → `dist/` |
| `npm run preview` | 预览构建产物 |
| `npm run typecheck` | 只做类型检查，不产出文件 |

## 目录结构

```
src/
  api/client.ts            # HTTP 客户端 + SSE 解析（本项目最有含量的一块）
  types/contracts.ts       # 与后端 Pydantic 对齐的类型，逐字段标注契约来源
  state/machine.ts         # 9 节点状态机的前端镜像，用于进度可视化
  hooks/useDiagnosisStream.ts  # 诊断流程状态管理（useReducer）
  components/
    StateMachineView.tsx   # 状态机 + 辩论环可视化
    ResultView.tsx         # 结果渲染（严格按"没有的字段就不渲染"）
  pages/DiagnosePage.tsx   # 诊断页
```

## 几个刻意的技术选择

### SSE 用 fetch + ReadableStream 手写，不用 EventSource

三个原因，缺一不可：

1. **EventSource 只支持 GET** —— 而 `/diagnose/stream` 是 POST。故障描述可能很长，
   还可能带 base64 图片，塞进 URL 既不现实也会撞上代理的 URL 长度限制；
2. **EventSource 无法自定义请求头** —— 带不了 `X-API-Key`，后端开了鉴权就用不了；
3. **EventSource 断线会自动重连** —— 对诊断这种"重连就重跑一遍、每次烧 6~9 次 LLM 调用"
   的场景，自动重连是有害的。

手写解析时有一个最容易踩的坑：**一个 SSE 消息可能被 TCP 切成多个 chunk，
一个 chunk 里也可能含多条消息**。所以必须在循环外累积 buffer、以空行分隔，
不能按 chunk 直接解析。`client.ts` 里对此有注释。

### 类型手写而不是用 openapi-typescript 生成

后端用的是中文键名（`根因判断` / `工单编号` …），这些是**跨层契约**。
自动生成会把键名原样搬过来但丢掉语义，反而看不出哪个字段是"降级时可能整体缺失"的。
手写一份并在每个类型上标注「契约来源：agents.py :: XXXOutput」，
改后端时能一眼找出前端要同步的地方。

### 不引入状态管理库

状态是单一的、由 reducer 收敛的，`useReducer` 已经足够表达。
引入 Redux/Zustand 只会让"状态从哪来"更难讲清。

### 降级工单不补空章节

`ResultView` 里所有工单字段都是可选的，缺什么就不渲染什么。
这是项目级硬约束（与后端 `workorder_export` 口径一致）：
没有依据的字段补出空的"维修方案"，比没有这个章节更危险——操作工可能照着一张
内容为空的工单去拆机。

## 已知限制

- 本次只切入**诊断页**；历史页与统计页仍由 Streamlit 提供（8501）。
  接口（`/records`、`/stats`）已就绪，迁移是纯前端工作。
- 移动端适配只做了基础响应式，未针对触屏优化。
- 无单元测试。SSE 解析与状态归约是纯函数，适合补测试；
  当前依赖后端侧的 `tests/test_graph_abort_and_sse.py` 覆盖接口契约。

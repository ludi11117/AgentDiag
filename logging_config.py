import sys
import threading
import structlog
from config import settings


def configure_logging():
    """配置 structlog 结构化日志"""
    timestamper = structlog.processors.TimeStamper(fmt="ISO", utc=False)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.format_exc_info,
    ]

    if settings.LOG_JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 配置标准库 logging
    import logging
    handler = logging.StreamHandler(sys.stdout)
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))

    # 抑制噪音库的日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)


def get_logger(name: str = None):
    """获取结构化日志记录器"""
    return structlog.get_logger(name)


# Token 使用统计上下文管理器
class TokenTracker:
    """追踪单次诊断的 Token 使用量"""

    def __init__(self, correlation_id: str = None):
        self.correlation_id = correlation_id
        self.usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "llm_calls": 0,
            # 其中有多少次拿不到服务端 usage、只能用本地估算 —— 用于判断统计可信度
            "estimated_calls": 0,
            "by_node": {}
        }
        self._current_node = None

    def start_node(self, node_name: str):
        self._current_node = node_name
        if node_name not in self.usage["by_node"]:
            self.usage["by_node"][node_name] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "calls": 0,
                # 节点整体耗时（含检索、规则计算等非 LLM 部分）
                "duration_ms": 0.0
            }

    def record_node_duration(self, node_name: str, duration_ms: float):
        """累加节点耗时。

        Token 统计只能回答"这次花了多少钱"，回答不了"为什么这次这么慢"。
        耗时和 Token 一样按节点归因，才能定位是检索慢还是模型慢。
        """
        node = self.usage["by_node"].get(node_name)
        if node is not None:
            node["duration_ms"] = round(node.get("duration_ms", 0.0) + duration_ms, 1)

    def add_usage(self, prompt: int, completion: int, estimated: bool = False):
        self.usage["prompt_tokens"] += prompt
        self.usage["completion_tokens"] += completion
        self.usage["total_tokens"] += prompt + completion
        self.usage["llm_calls"] += 1
        if estimated:
            self.usage["estimated_calls"] += 1
        if self._current_node:
            node = self.usage["by_node"][self._current_node]
            node["prompt_tokens"] += prompt
            node["completion_tokens"] += completion
            node["total_tokens"] += prompt + completion
            node["calls"] += 1

    def get_summary(self) -> dict:
        """返回当前用量快照。

        必须**深一层**拷贝 by_node：`dict.copy()` 是浅拷贝，调用方拿到的
        `by_node` 与 tracker 内部是同一个对象。而这份快照会被放进诊断结果、
        存进 session_state、写进数据库——一旦后续还有 LLM 调用，
        这份"历史快照"就会跟着变，历史记录与实际发生过的调用对不上。
        """
        summary = dict(self.usage)
        summary["by_node"] = {k: dict(v) for k, v in self.usage["by_node"].items()}
        return summary

    def log_summary(self, logger=None):
        if logger is None:
            logger = get_logger("token_usage")
        logger.info(
            "token_usage_summary",
            correlation_id=self.correlation_id,
            total_tokens=self.usage["total_tokens"],
            by_node=self.usage["by_node"]
        )


# 全局 token tracker 存储 (用于跨节点累积)
# Streamlit / FastAPI 都是多线程环境，dict 的 get-or-create 必须加锁，否则同一
# correlation_id 可能被并发创建出多个 tracker，token 统计随之丢失。
_token_trackers = {}
_tracker_lock = threading.Lock()


def get_token_tracker(correlation_id: str) -> TokenTracker:
    with _tracker_lock:
        if correlation_id not in _token_trackers:
            _token_trackers[correlation_id] = TokenTracker(correlation_id)
        return _token_trackers[correlation_id]


def clear_token_tracker(correlation_id: str):
    with _tracker_lock:
        _token_trackers.pop(correlation_id, None)
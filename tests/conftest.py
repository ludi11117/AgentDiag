import os
import sys
from pathlib import Path

import pytest

# 让测试可以在无真实密钥的环境下导入 config/agents（不发起任何网络请求）
os.environ.setdefault("SILICONFLOW_API_KEY", "test-key-for-unit-tests")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须在 sys.path 就绪之后再导入
import database  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """把数据库指到临时文件，避免污染真实的 diagnosis_history.db。

    连接是 thread-local 缓存的，所以切换路径前必须先关掉当前线程的连接。
    """
    database.close_db_connections()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(database, "_db_initialized", False)
    yield database
    database.close_db_connections()

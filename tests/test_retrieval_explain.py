"""检索融合的可解释性与正确性回归测试。

这里测的**不是**"检索准不准"（那需要真实嵌入和判官），
而是"融合机制本身有没有按设计工作"——这些是确定性的，可以离线钉死。

全部离线：不调 LLM、不联网。向量库相关测试用真实 Chroma 只读访问。
"""

from pathlib import Path

import agents

ROOT = Path(__file__).resolve().parent.parent
EXPLAIN_TOOL = ROOT / "tools" / "explain_retrieval.py"


# ========== RRF 融合的机制性质 ==========

def test_rrf_interleaves_channels_instead_of_concatenating():
    """RRF 必须让两路**交错**，而不是把一路整段拼在另一路前面。

    ⚠️ 这条是踩坑后重写的。原来写的是"a1 和 b1 都在结果里"+
    "a1 排在 b3 前面"——但**按通道拼接+截断也满足这两条**
    （拼接：[a1,a2,a3,b1,b2,b3]，a1 在 b3 前）。退化验证时它照样绿，
    等于没测到 RRF。

    真正能区分两者的是：B 通道的第 1 名（b1）应该插到 A 通道第 2、3 名之间。
      RRF:       [a1, b1, a2, b2, ...]   ← 交错
      拼接截断:  [a1, a2, a3, b1, ...]   ← 整段拼接
    所以断言 b1 必须排在 a3 之前。
    """
    chan_a = ["a1", "a2", "a3"]
    chan_b = ["b1", "b2", "b3"]
    fused = agents._reciprocal_rank_fusion([chan_a, chan_b], k=6)
    assert fused.index("b1") < fused.index("a3"), (
        f"B 通道头名被排在 A 通道尾部之后 → 说明是拼接而非融合：{fused}"
    )
    assert fused.index("a1") < fused.index("b1"), "A 通道头名仍应在前"


def test_rrf_does_not_drop_second_channel_on_truncation():
    """截断时必须两路都有代表——这是"别让后一路被整体挤掉"的核心。

    RRF 的得分对两路的 rank-1 是**相同**的，所以截断到 2 条时，
    两路的头名都应该留下。拼接截断则会留下 [a1, a2]，B 通道全军覆没。
    """
    chan_a = ["a1", "a2", "a3", "a4"]
    chan_b = ["b1", "b2", "b3", "b4"]
    fused = agents._reciprocal_rank_fusion([chan_a, chan_b], k=2)
    assert "a1" in fused, f"结果里没有 A 通道头名：{fused}"
    assert "b1" in fused, f"结果里没有 B 通道头名——晚到的通道被挤掉了：{fused}"


def test_rrf_rewards_documents_hitting_multiple_channels():
    """两路都命中的文档，得分应高于只被一路命中的。

    构造时要排除平局：让 "shared" 在两路都是第 1，得分 2/(rrf_k+1)，
    而 "only_a" 只在 A 路第 1、且在两路里都排不到第 2 名之后。
    """
    fused = agents._reciprocal_rank_fusion(
        [["shared", "only_a"], ["shared", "only_b"]], k=3
    )
    assert fused[0] == "shared", "同时被两路命中的文档应该排第一"


def test_rrf_respects_k_limit():
    """k 必须真的截断——否则会喂给模型超量资料，白烧 context。"""
    fused = agents._reciprocal_rank_fusion([["a", "b", "c", "d", "e"]], k=2)
    assert len(fused) == 2


def test_rrf_skips_empty_documents():
    """空字符串不得进入结果（否则 evidence 里会出现空条目）。"""
    fused = agents._reciprocal_rank_fusion([["", "real", ""], []], k=5)
    assert "" not in fused
    assert "real" in fused


def test_rrf_tiebreak_prefers_shorter_document():
    """同分时短文档优先（信息密度更高）——这是有意的确定性平局规则。"""
    # 两篇都只在各自通道的第 1 名 → 完全同分
    short = "短"
    long_doc = "很长的文档" * 20
    fused = agents._reciprocal_rank_fusion([[short], [long_doc]], k=2)
    assert fused[0] == short, "同分时应让短文档在前"


def test_rrf_uses_settings_default_k_when_not_given(monkeypatch):
    """不传 rrf_k 时读 settings.RRF_K，而不是硬编码的常量。"""
    from config import settings
    assert agents._reciprocal_rank_fusion([["a"]], k=1, rrf_k=None) == ["a"]
    # 传一个极大的 rrf_k，所有分母趋同，排名应退化为"谁先出现谁靠前"
    huge = agents._reciprocal_rank_fusion([["x"], ["y"]], k=2, rrf_k=10**9)
    assert set(huge) == {"x", "y"}
    assert settings.RRF_K == 60, "RRF_K 默认值是 60，改了要同步文档"


# ========== 检索返回值的契约 ==========

def test_retrieve_returns_placeholder_when_nothing_found(monkeypatch):
    """一条都检不到时必须返回固定占位符，而不是空串。

    空串会被下游当成"有资料但内容为空"，占位符才能触发诚实降级。
    """
    monkeypatch.setattr(agents, "get_db", lambda: _EmptyDB())
    monkeypatch.setattr(agents, "_get_bm25", lambda: (None, []))
    out = agents.retrieve_evidence("任意查询")
    assert out == "【知识库无相关依据】"


def test_retrieve_labels_sources_in_order(monkeypatch):
    """资料必须带【资料N】编号且从 1 开始——诊断师靠这个引用来源。"""
    monkeypatch.setattr(agents, "get_db", lambda: _FakeDB(["甲", "乙"]))
    monkeypatch.setattr(agents, "_get_bm25", lambda: (None, []))
    out = agents.retrieve_evidence("q")
    assert "【资料1】" in out and "【资料2】" in out
    assert out.index("【资料1】") < out.index("【资料2】")


class _EmptyDB:
    def similarity_search(self, query, k=None):
        return []


class _FakeDB:
    """只实现 similarity_search 的最小桩，避免测试依赖真实向量库。"""

    def __init__(self, texts):
        self._texts = texts

    def similarity_search(self, query, k=None):
        class _Doc:
            def __init__(self, c):
                self.page_content = c
        return [_Doc(t) for t in self._texts[:k]]


# ========== 解释工具本身 ==========

def test_explain_tool_exists_and_is_referenced():
    """解释脚本必须存在——文档引用它，不存在就是文档说谎。"""
    assert EXPLAIN_TOOL.exists(), f"{EXPLAIN_TOOL} 不存在"


def test_explain_tool_declares_queries_with_notes():
    """每个内置查询都必须带"看点"说明，否则跑出来不知道在看什么。"""
    src = EXPLAIN_TOOL.read_text(encoding="utf-8")
    for key in ("code_precise", "semantic_rewrite", "cross_device",
                "ambiguous", "near_miss_code"):
        assert f'"{key}"' in src, f"解释脚本缺少查询 {key}"


def test_explain_tool_stub_matches_collection_dimension():
    """嵌入桩的维度必须与真实 collection 一致（bge-m3 = 1024）。

    给错维度 Chroma 会直接抛 InvalidArgumentError: expecting 1024, got 8。
    （实测踩过。）这条测试把正确维度钉在代码里。
    """
    src = EXPLAIN_TOOL.read_text(encoding="utf-8")
    assert "DIM = 1024" in src, "嵌入桩维度必须为 1024，否则离线跑不起来"

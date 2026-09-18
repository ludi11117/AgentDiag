"""检索可解释化：把"混合检索到底怎么选出这几条资料"摊开给人看。

用途：**不用 API key、不花钱、不联网**。
它加载**真实的本地向量库**（`chroma_db/`），用**真实的**
`agents._reciprocal_rank_fusion` 做融合，只在需要嵌入新查询时打桩
（否则要联网调 embedding API）。

为什么要有这个脚本：
    RAG 项目最容易被追问的就是"检索是怎么调的、为什么出来的是这几条"。
    只看最终 evidence 字符串回答不了——那已经把两路排名和融合过程抹掉了。
    这个脚本把三件事分别打出来：

      1. 向量通道单独排出来是什么
      2. BM25 通道单独排出来是什么
      3. RRF 融合后各自贡献了多少分、最终谁入选

    有了它就能指着屏幕说："BM25 把带报警代码的那条顶上来了，
    向量把语义改写的那条顶上来了，融合后两条都在，谁也没被挤掉。"

用法：
    venv\\Scripts\\python.exe tools\\explain_retrieval.py                    # 全部内置查询
    venv\\Scripts\\python.exe tools\\explain_retrieval.py "主轴 异响 E-203"    # 自定义查询
    venv\\Scripts\\python.exe tools\\explain_retrieval.py --list             # 看内置查询
    venv\\Scripts\\python.exe tools\\explain_retrieval.py --json             # 导出报告
"""

import json
import os
import sys
from pathlib import Path

# 必须在 import config 之前设置：config.py 里 SILICONFLOW_API_KEY 是必填字段。
# 本脚本只在**需要嵌入新查询**时才打桩，加载已有向量库不需要 key。
os.environ.setdefault("SILICONFLOW_API_KEY", "explain-retrieval-offline")
os.environ.setdefault("LOG_LEVEL", "WARNING")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agents                      # noqa: E402
from config import settings        # noqa: E402
from logging_config import configure_logging   # noqa: E402

configure_logging()

W = 84

# ========== 内置查询 ==========
# 每条都刻意标注"想看什么"——否则跑出来一堆排名不知道在看什么。

QUERIES = {
    "code_precise": (
        "精确代码命中",
        "数控机床主轴 E-203 异响",
        "BM25 应该把带 E-203 的那条顶到最前面（精确 token）",
    ),
    "semantic_rewrite": (
        "语义改写",
        "那台机床主轴转起来一顿一顿的，还有点烫",
        "向量通道的强项：用户没说'转速不稳''温升'，但语义能对上",
    ),
    "cross_device": (
        "跨设备干扰",
        "空压机振动大，报警 A-203",
        "空压机与主轴的报警码/症状都不同，看会不会串味",
    ),
    "ambiguous": (
        "无代码模糊描述",
        "设备坏了",
        "两边都可能低分，看融合后剩几条、会不会返回无依据",
    ),
    "near_miss_code": (
        "近似代码",
        "主轴 E-230 振动",
        "E-230 与 E-203 是不同故障，看检索能否区分",
    ),
}


def hr(ch="─"):
    print(ch * W)


def title(text):
    print()
    print("═" * W)
    print(f"  {text}")
    print("═" * W)


# ========== 嵌入打桩 ==========
# 向量库已经建好（chroma_db/），加载不需要联网；
# 但 similarity_search 要先把**查询**嵌成向量，那一步会调 API。
# 离线做法：返回一个固定向量——排名会失真，所以脚本会明确标注这一点。

def install_embedding_stub():
    """把查询嵌入换成固定向量，让脚本可以完全离线跑。

    ⚠️ 关键：嵌入函数是**在 get_db() 构造单例时绑定进去的**，光替换
    `agents.get_embeddings` 不够——已经建好的 `_db` 内部持有旧引用，
    仍然会去联网。必须把 `_db` 单例一起清掉，让它用桩重建。
    （这个坑实测踩过：只换 get_embeddings 会直接抛网络错误。）

    返回 (原嵌入函数, 原 db 单例) 以便还原。
    **排名会失真**——这不是"真实检索结果"，而是"管道结构的演示"。
    要看真实排名，去掉这个桩并配置真 key。
    """
    class _FixedEmbeddings:
        """返回常量向量。仅用于让管道跑通，排序无语义。

        维度必须与已有 collection 匹配——本项目嵌入是 BAAI/bge-m3（1024 维），
        给 8 维会被 Chroma 直接拒绝（InvalidArgumentError: expecting 1024）。
        """

        DIM = 1024

        def embed_documents(self, texts):
            return [[0.1] * self.DIM for _ in texts]

        def embed_query(self, text):
            return [0.1] * self.DIM

    original_emb = agents.get_embeddings
    original_db = agents._db
    agents.get_embeddings = lambda: _FixedEmbeddings()
    agents._db = None            # 逼单例用桩重建
    return original_emb, original_db


def restore_embeddings(saved):
    original_emb, original_db = saved
    agents.get_embeddings = original_emb
    agents._db = original_db


def analyze_query(label: str, note: str, query: str) -> dict:
    """跑一次检索，把三路排名分别取出来。"""
    db = agents.get_db()
    k = settings.RETRIEVAL_K

    vector_docs = db.similarity_search(query, k=k)
    vector_texts = [d.page_content for d in vector_docs]

    bm25_index, doc_texts = agents._get_bm25()
    bm25_texts = []
    if bm25_index is not None and doc_texts:
        import jieba
        tokenized = list(jieba.cut(query))
        scores = bm25_index.get_scores(tokenized)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        bm25_texts = [doc_texts[i] for i in order[:settings.BM25_K] if scores[i] > 0]

    fused_texts = agents._reciprocal_rank_fusion([bm25_texts, vector_texts], k)

    # 逐条算 RRF 贡献，这样能说清"这条为什么入选"
    contributions = {}
    for chan, ranked in (("bm25", bm25_texts), ("vector", vector_texts)):
        for rank, doc in enumerate(ranked, start=1):
            contributions.setdefault(doc, {"bm25_rank": None, "vector_rank": None, "score": 0.0})
            contributions[doc][f"{chan}_rank"] = rank
            contributions[doc]["score"] += 1.0 / (settings.RRF_K + rank)
    for doc in contributions:
        contributions[doc]["score"] = round(contributions[doc]["score"], 6)
        contributions[doc]["selected"] = doc in fused_texts

    return {
        "query_key": label,
        "query_note": note,
        "query": query,
        "params": {"RETRIEVAL_K": k, "BM25_K": settings.BM25_K, "RRF_K": settings.RRF_K},
        "bm25_ranked": bm25_texts,
        "vector_ranked": vector_texts,
        "fused": fused_texts,
        "contributions": contributions,
        "total_chunks_in_kb": len(doc_texts) if bm25_index is not None else 0,
    }


# ========== 打印 ==========

def _short(text, limit=58):
    s = " ".join(str(text).split())
    return s[:limit] + "…" if len(s) > limit else s


def print_channel(name, ranked, total):
    print(f"\n  ■ 通道：{name}（取前 {len(ranked)} 条 / 库中共 {total} 块）")
    if not ranked:
        print("      （本通道无命中）")
        return
    for i, doc in enumerate(ranked, 1):
        print(f"      {i:>2}. {_short(doc)}")


def print_fusion(report):
    print(f"\n  ■ RRF 融合（rrf_k={report['params']['RRF_K']}）")
    print(f"      {'排名':<4} {'入选':<5} {'BM25排':<7} {'向量排':<7} {'融合分':<9} 内容")
    print("      " + "─" * 76)
    rows = sorted(report["contributions"].items(), key=lambda kv: -kv[1]["score"])
    for i, (doc, c) in enumerate(rows, 1):
        b = c["bm25_rank"] if c["bm25_rank"] else "—"
        v = c["vector_rank"] if c["vector_rank"] else "—"
        sel = "✓" if c["selected"] else ""
        print(f"      {i:<4} {sel:<5} {str(b):<7} {str(v):<7} {c['score']:<9.6f} {_short(doc, 40)}")


def run_query(key, spec, want_json=False, collected=None):
    label, query, note = spec
    title(f"{label} —— {query!r}")
    print(f"  看点：{note}")
    report = analyze_query(key, note, query)

    p = report["params"]
    print(f"\n  参数：RETRIEVAL_K={p['RETRIEVAL_K']}  BM25_K={p['BM25_K']}  RRF_K={p['RRF_K']}"
          f"  知识库共 {report['total_chunks_in_kb']} 块")

    print_channel("BM25 关键词", report["bm25_ranked"], report["total_chunks_in_kb"])
    print_channel("向量语义", report["vector_ranked"], report["total_chunks_in_kb"])
    print_fusion(report)

    print(f"\n  ■ 最终喂给诊断师的 evidence：{len(report['fused'])} 条")
    if not report["fused"]:
        print("      （空 → 会返回【知识库无相关依据】，走诚实降级）")

    hr()
    if collected is not None:
        collected.append(report)


def main():
    args = sys.argv[1:]

    if "--list" in args:
        for k, (label, q, note) in QUERIES.items():
            print(f"  {k:<18} {label} —— {q!r}")
            print(f"  {'':<18} 看点：{note}")
        return

    want_json = "--json" in args
    custom = [a for a in args if not a.startswith("-") and a not in QUERIES]

    print("=" * W)
    print("  FlawScope 检索可解释化（混合检索 = 向量 + BM25 + RRF 融合）")
    print(f"  向量库：{settings.CHROMA_PERSIST_DIR}")
    print("  ⚠️ 本脚本打桩了查询嵌入（否则要联网调 API）——**排名会失真**。")
    print("     它演示的是'管道结构'：两路怎么各自排名、融合怎么定名额。")
    print("     要看真实排名，配好真 key 后删掉 install_embedding_stub() 调用。")
    print("=" * W)

    original = install_embedding_stub()
    collected = []
    try:
        if custom:
            for i, q in enumerate(custom, 1):
                run_query(f"custom{i}", (f"自定义查询 {i}", q, "用户指定"), want_json, collected)
        else:
            for k, spec in QUERIES.items():
                run_query(k, spec, want_json, collected)
    finally:
        restore_embeddings(original)

    if want_json:
        out = Path(__file__).resolve().parent.parent / "retrieval_explain.json"
        payload = {
            "note": "由 tools/explain_retrieval.py --json 生成；查询嵌入已打桩，排名失真，仅演示管道结构",
            "params": {"RETRIEVAL_K": settings.RETRIEVAL_K, "BM25_K": settings.BM25_K, "RRF_K": settings.RRF_K},
            "queries": collected,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已导出：{out}（{len(collected)} 个查询）")
    else:
        print("\n提示：加 --json 导出报告；传自定义查询如 explain_retrieval.py \"主轴 E-203\"。")


if __name__ == "__main__":
    main()

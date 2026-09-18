"""状态机结构自检：图与文档、文档与实现必须对得上。

为什么值得单独测：状态机是本项目的骨架，而**文档最容易随时间腐烂**——
改了一个路由忘了改图，下次照着图排查就会被带偏。
这里把"实现里有什么"与"文档里写了什么"做确定性比对。

全部离线，不调 LLM、不联网。
"""

import re
from pathlib import Path

import pytest

import orchestrator

ROOT = Path(__file__).resolve().parent.parent
DIAGRAM = ROOT / "docs" / "状态机流转图.md"
TRACE_TOOL = ROOT / "tools" / "trace_diagnosis.py"


def _graph_nodes() -> set:
    """从**编译后**的真实图对象里取节点名（而不是从源码正则猜）。

    注意要用 `orchestrator.app`（CompiledStateGraph）——`orchestrator.graph`
    只是还没编译的 StateGraph builder，它没有 `get_graph()`。
    """
    return set(orchestrator.app.get_graph().nodes.keys())


def _graph_edges() -> set:
    """(源, 目标) 集合。编译后 `__start__` / `__end__` 会作为哨兵节点出现。"""
    return {(e.source, e.target) for e in orchestrator.app.get_graph().edges}


def test_all_declared_nodes_exist_in_graph():
    """代码里声明的 10 个节点必须都在图里。"""
    expected = {
        "extract_info", "check_info", "retrieve", "diagnose", "review",
        "rebuttal", "final_review", "cost", "workorder", "human_review",
    }
    missing = expected - _graph_nodes()
    assert not missing, f"这些节点没有加进图里：{missing}"


def test_terminal_human_review_is_not_a_dead_end():
    """转人工必须还能走到工单，不能是死胡同。

    这是本项目的硬约束：每个降级分支都要让用户拿到一张带风险标记的工单，
    而不是一句报错。human_review → cost → workorder 这条边断了就违反约束。
    """
    edges = _graph_edges()
    assert ("human_review", "cost") in edges, "human_review 没有接到 cost，会变成死胡同"
    assert ("cost", "workorder") in edges, "cost 没有接到 workorder"
    assert ("workorder", "__end__") in edges, "workorder 没有接到 END"


def test_every_conditional_route_returns_declared_target():
    """每个条件路由函数返回的目标，必须在 add_conditional_edges 里声明过。

    典型事故：路由函数返回 "cost"，但映射表里只有 "review"/"rebuttal"，
    LangGraph 会在**运行时**才抛错——这里提前抓住。
    """
    cases = [
        (orchestrator.route_after_check_info, {"status": "info_sufficient"}, {"retrieve", "need_more_info", "cost"}),
        (orchestrator.route_after_check_info, {"status": "llm_failed"}, {"retrieve", "need_more_info", "cost"}),
        (orchestrator.route_after_diagnose, {"status": "diagnosed"}, {"review", "cost"}),
        (orchestrator.route_after_review, {"review": {"审核意见": "通过"}}, {"cost", "rebuttal", "human_review"}),
        (orchestrator.route_after_final_review, {"final_review": {"审核意见": "通过"}}, {"cost", "rebuttal"}),
    ]
    for fn, state, allowed in cases:
        # 补上路由函数可能读到的默认字段，避免 KeyError 干扰断言
        full = {"debate_round": 0, "max_debate_rounds": 3, "diagnosis": {}, "status": ""}
        full.update(state)
        got = fn(full)
        assert got in allowed, f"{fn.__name__}{state} → {got!r} 不在声明目标 {allowed} 内"


def test_degraded_diagnosis_never_enters_debate():
    """诚实降级的诊断不得进入辩论环节。

    否则辩论会基于"无依据"的诊断凭空编造根因——这条路由是诚实降级的闸门。
    """
    state = {
        "diagnosis": {"根因判断": "知识库无相关依据，无法诊断"},
        "review": {"审核意见": "不通过"},
        "debate_round": 0,
        "max_debate_rounds": 3,
    }
    assert orchestrator.route_after_review(state) == "human_review"


def _diagram_table_rows() -> dict:
    """从流转图的**节点表**里取出 {节点名: 整行文本}。

    ⚠️ 只检查"文档里出现过这个名字"是不够的——Mermaid 图里也会出现节点名，
    把表格行改坏时测试照样绿（实测踩过，退化验证抓出来的）。
    必须**精确到表格行**。

    也**只认「节点名」那一列**：文档里还有别的表格同样用反引号
    （如退出路径表的 `need_more_info` 等状态值），把那些当成节点名会误报。
    节点表的标志是表头含"节点名"。
    """
    lines = DIAGRAM.read_text(encoding="utf-8").splitlines()
    rows = {}
    in_node_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and "节点名" in stripped:
            in_node_table = True
            continue
        if in_node_table:
            if not stripped.startswith("|"):
                in_node_table = False       # 表格结束
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) < 2:
                continue
            name_cell = cells[1]            # 第 1 列是序号，第 2 列是节点名
            if name_cell.startswith("`") and name_cell.endswith("`"):
                rows[name_cell.strip("`")] = stripped
    return rows


def test_diagram_lists_every_implementation_node():
    """流转图的**节点表**必须列出实现里的每个节点。

    文档腐烂就是从这里开始的：改了 `add_node` 忘了改图，下次照着图排查就被带偏。
    """
    rows = _diagram_table_rows()
    missing = [n for n in _graph_nodes()
               if n not in ("__start__", "__end__") and n not in rows]
    assert not missing, f"docs/状态机流转图.md 的节点表缺少：{missing}"


def test_diagram_does_not_list_phantom_nodes():
    """反向检查：节点表里不能出现实现中不存在的节点名。

    只查"实现有的文档有没有"会漏掉反向错误——文档里写了个早已删掉的节点，
    读者会以为它还在。这一条同样被退化验证确认过。
    """
    rows = _diagram_table_rows()
    known = _graph_nodes() | {"__start__", "__end__"}
    phantom = [n for n in rows if n not in known]
    assert not phantom, f"docs/状态机流转图.md 的节点表出现了不存在的节点：{phantom}"


def test_diagram_documents_every_terminal_status():
    """流转图必须提到每个终态，否则读者不知道一条岔路通向什么。"""
    text = DIAGRAM.read_text(encoding="utf-8")
    for status in ("need_more_info", "llm_failed", "insufficient_knowledge", "pending_human_review"):
        assert status in text, f"docs/状态机流转图.md 没有说明终态 {status}"


@pytest.mark.parametrize("tool_path", [TRACE_TOOL])
def test_trace_tool_exists_and_has_scenarios(tool_path):
    """演示脚本必须存在，且场景数与文档口径一致。"""
    assert tool_path.exists(), f"{tool_path} 不存在——文档引用了它就会说谎"
    src = tool_path.read_text(encoding="utf-8")
    found = re.findall(r'^\s{4}"(\w+)": \(', src, re.M)
    assert len(found) >= 6, f"trace_diagnosis.py 只有 {len(found)} 个场景，文档写的是 6 个"
    for key in ("happy", "followup", "no_knowledge", "guard", "llm_down", "debate"):
        assert key in found, f"trace_diagnosis.py 缺少场景 {key}"

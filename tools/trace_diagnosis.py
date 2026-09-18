"""离线演示：把状态机跑一遍，逐个节点打印输入与输出。

用途：**不用 API key、不花钱、不联网**，就能亲眼看见 LangGraph 状态机是怎么流转的。
它跑的是**真实的 orchestrator.app**，只把"调模型"那几处替换成固定回答。

用法：
    venv\\Scripts\\python.exe tools\\trace_diagnosis.py            # 跑全部 6 个场景
    venv\\Scripts\\python.exe tools\\trace_diagnosis.py happy      # 只跑指定场景
    venv\\Scripts\\python.exe tools\\trace_diagnosis.py --list     # 看有哪些场景
    venv\\Scripts\\python.exe tools\\trace_diagnosis.py --json     # 导出机器可读 trace

为什么要有这个脚本：
    读代码只能看到"应该怎么走"，跑一遍才能看到"实际怎么走"。
    尤其是几条提前退出的岔路（追问 / 降级 / 失败短路），
    光看代码很难建立直觉。

关于耗时与 token：
    真实运行时这里会有数字；本脚本因为桩掉了模型，耗时只反映"节点本身"的
    分发开销（毫秒级），token 恒为 0。**这不是 bug，是桩的必然结果**——
    每次运行都会在表头明确标注，避免把演示数据误当成真实性能。
"""

import json
import os
import sys
from pathlib import Path

# 必须在 import config 之前设置：config.py 里 SILICONFLOW_API_KEY 是必填字段，
# 缺失会在 import 时直接抛错。这里塞个假值——本脚本不会真的发请求。
os.environ.setdefault("SILICONFLOW_API_KEY", "trace-demo-no-network")
# 只留 WARNING 以上：info 日志会把逐节点的演示输出冲散，
# 而 warning 恰好是"护栏拦下了什么"的信号，正是要看的东西。
os.environ.setdefault("LOG_LEVEL", "WARNING")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agents                      # noqa: E402
import orchestrator                # noqa: E402
from logging_config import (  # noqa: E402
    clear_token_tracker,
    configure_logging,
    get_token_tracker,
)

# 不调这个的话，structlog 走默认配置会把 info 日志全打出来，把演示输出冲散。
configure_logging()

# ========== 工具：打印 ==========

W = 74


def hr(ch="─"):
    print(ch * W)


def title(text):
    print()
    hr("═")
    print(f"  {text}")
    hr("═")


def node_line(label, delta, state, elapsed_ms=None, tokens=None):
    """打印一个节点的执行结果"""
    metric = ""
    if elapsed_ms is not None:
        metric += f"  耗时 {elapsed_ms:>7.1f} ms"
    if tokens is not None:
        metric += f"  token {tokens:>6}"
    print(f"\n  ▶ {label}{metric}")
    if not delta:
        print("      （无输出）")
    else:
        for k, v in delta.items():
            print(f"      {k:<18} = {_brief(v)}")
    print(f"      {'状态':<18} → {state.get('status')}")


def _brief(v, limit=64):
    s = str(v).replace("\n", " ")
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


# ========== 打桩：把"调模型"换成固定回答 ==========
# 注意：is_info_sufficient / generate_followup_question / is_equipment_in_evidence
# 这几个是**纯规则函数**，保持真实实现——它们本来就不调模型。

def install_stubs(scenario: str):
    """按场景安装桩函数"""

    def stub_extract(user_input, correlation_id=None):
        if scenario == "llm_down":
            return None                      # None = 模型调用失败（≠ 信息不足）
        if scenario == "followup":
            return {}                        # {} = 模型答了，但抽不出信息
        return {
            "设备类型": "数控机床主轴电机",
            "报警代码": "E-203",
            "故障现象": ["转速不稳", "异响", "温升异常"],
            "排除条件": [],
        }

    def stub_retrieve(query, k=None, correlation_id=None):
        if scenario == "no_knowledge":
            return "【知识库无相关依据】"
        if scenario == "guard":
            # 故意给一份"设备对不上"的资料：报警代码是 E-101，而用户说的是 E-203。
            # 确定性护栏会因此拦下这次诊断——这就是"防跨设备幻觉"那道防线。
            return (
                "【资料1】\n一、液压站\n"
                "1. 溢流阀卡滞导致压力异常\n"
                "2. 液压油污染\n"
            )
        return (
            "【资料1】数控机床主轴电机 报警 E-203 故障处理\n"
            "一、主轴电机\n"
            "1. 负载过大或负载不平衡\n"
            "2. 轴承损坏或润滑不良\n"
            "【资料2】\n二、冷却系统\n"
            "1. 冷却风扇故障\n"
        )

    def stub_diagnose(evidence, fault, exclusion_list=None, correlation_id=None):
        return {
            "报警代码": "E-203",
            "根因判断": "原因2：轴承损坏或润滑不良",
            "依据": "资料1 第 2 条",
            "排查建议": ["停机检查主轴轴承", "补充润滑脂"],
        }

    def stub_review(diagnosis, correlation_id=None):
        if scenario == "debate":
            return {"审核意见": "不通过", "理由": "证据不足，未排除负载问题", "风险提示": "中"}
        return {"审核意见": "通过", "理由": "依据充分", "风险提示": "低"}

    def stub_cost(diagnosis, review, correlation_id=None):
        # 用真实的 calculate_cost 算钱，这样打印出来的数字是真的
        parts, hours = ["主轴轴承", "润滑脂"], 2.0
        bd = agents.calculate_cost(parts, hours)
        hint = ""
        if bd["未知备件"]:
            hint = "以下备件不在价格表中，未计入报价，需人工核价：" + "、".join(bd["未知备件"])
        return {
            "备件清单": parts,
            "预计工时": f"{hours}小时",
            "预计成本": f"{bd['总费用']}元",
            "成本明细": bd,
            "计费提示": hint,
        }

    def stub_workorder(diagnosis, review, cost, correlation_id=None):
        return {
            "工单编号": "WO-DEMO-001",
            "故障现象": "主轴转速不稳、异响、温升异常",
            "根因": diagnosis.get("根因判断", ""),
            "维修方案": "更换主轴轴承并补充润滑脂",
            "备件清单": cost.get("备件清单", []),
            "预计成本": cost.get("预计成本", ""),
            "安全注意事项": "断电挂牌后作业",
        }

    def stub_rebuttal(diagnosis, review, evidence, fault, correlation_id=None):
        return {
            "行动": "反驳",
            "最终根因": "原因2：轴承损坏或润滑不良",
            "依据": "资料1 第 2 条明确列出轴承损坏",
            "置信度": 85,
            "反驳理由": "负载问题已在排除条件中剔除，剩余可能只有轴承",
        }

    def stub_review_final(original_diagnosis, rebuttal, correlation_id=None):
        if scenario == "debate":
            return {"审核意见": "不通过", "理由": "仍不认可", "置信度": 60, "风险提示": "高"}
        return {"审核意见": "通过", "理由": "补充证据后认可", "置信度": 90, "风险提示": "低"}

    # 全部挂到 orchestrator 上（节点函数是从它自己的模块命名空间里找这些名字的）
    orchestrator.extract_fault_info = stub_extract
    orchestrator.retrieve_evidence = stub_retrieve
    orchestrator.agent_diagnose = stub_diagnose
    orchestrator.agent_review = stub_review
    orchestrator.agent_cost = stub_cost
    orchestrator.agent_workorder = stub_workorder
    orchestrator.agent_rebuttal = stub_rebuttal
    orchestrator.agent_review_final = stub_review_final
    # 相关性核验：始终"验成了、且相关"，避免把演示绕进降级分支
    orchestrator.check_relevance = lambda *a, **kw: True


# ========== 场景定义 ==========

SCENARIOS = {
    "happy": (
        "正常路径", "信息充足 → 审核通过 → 出工单", "数控机床主轴异响，报警 E-203",
        "9 个节点走满；成本是 Python 算的：850+80+2×150 = 1230 元（模型不参与算术）",
    ),
    "followup": (
        "信息不足", "抽不出信息 → 停下来追问用户", "坏了",
        "在 check_info 处就结束，检索/诊断/成本全都没执行——硬猜不如问一句",
    ),
    "no_knowledge": (
        "知识库无依据", "检索为空 → 诚实降级，不编造根因", "某台没见过的设备，报警 X-999",
        "诊断师根本没被调用（注意只有 warning 日志，没有 diagnose_done）",
    ),
    "guard": (
        "设备对不上", "资料里是别的设备 → 确定性护栏拦下，不跨设备瞎猜",
        "数控机床主轴异响，报警 E-203",
        "资料讲的是液压站（E-101），与用户的 E-203 不符 → 护栏直接判无依据",
    ),
    "llm_down": (
        "模型服务异常", "抽取阶段就挂了 → 短路，不追问用户", "数控机床主轴异响",
        "关键：返回 None（模型失败）与返回 {}（信息不足）走的是两条完全不同的路",
    ),
    "debate": (
        "辩论不通过", "审核一直不通过 → 辩论到上限，标高风险", "数控机床主轴异响，报警 E-203",
        "注意节点编号会回到 ⑥⑦ 再走一遍——这就是状态机里的那个环",
    ),
}


def run_scenario(key: str, collect: list = None):
    """跑一个场景。

    collect 非空时把逐节点记录 append 进去，供 --json 导出机器可读 trace。
    """
    name, desc, user_input, watch = SCENARIOS[key]
    title(f"场景：{name} —— {desc}")
    print(f"  用户输入：{user_input!r}")
    print(f"  看点：{watch}")

    install_stubs(key)

    # 辩论场景把上限压到 2 轮，输出更短、更容易看清"回到 rebuttal"这个环
    max_rounds = 2 if key == "debate" else 3

    correlation_id = f"trace-{key}"
    original_max = orchestrator.settings.MAX_DEBATE_ROUNDS
    trace = {
        "scenario": key,
        "name": name,
        "user_input": user_input,
        "nodes": [],
    }
    try:
        # run_diagnosis_stream 会按 settings.MAX_DEBATE_ROUNDS 自己初始化状态，
        # 所以这里改的是设置而不是 state；演示完在 finally 里还原。
        orchestrator.settings.MAX_DEBATE_ROUNDS = max_rounds

        last = {}
        last_by_node = {}
        for label, snapshot in orchestrator.run_diagnosis_stream(
            user_input, correlation_id=correlation_id
        ):
            if label.startswith("🚀"):
                print("\n  ▶ 初始状态（还没有节点执行）")
                print(f"      {'状态':<18} → {snapshot.get('status')}")
                last = dict(snapshot)
                continue

            # 耗时直接取自 TokenTracker 的 node 归因——不要在这里用 time.perf_counter()
            # 自己测，那样测到的是"生成器两次 yield 之间的间隔"（含打印开销），
            # 会把演示耗时算虚，且与真实运行时记录的 duration_ms 不是同一个口径。
            elapsed_ms = _node_duration(correlation_id, last_by_node)
            tokens = _node_tokens(correlation_id, last_by_node)

            delta = {k: v for k, v in snapshot.items() if last.get(k) != v and k not in
                     ("user_input", "image_description", "max_debate_rounds", "correlation_id")}
            node_line(label, delta, snapshot, elapsed_ms, tokens)
            trace["nodes"].append({
                "label": label,
                "elapsed_ms": elapsed_ms,
                "tokens": tokens,
                "status": snapshot.get("status"),
                "changed_keys": sorted(delta.keys()),
            })
            last = dict(snapshot)

        final = last
        print()
        hr()
        print(f"  最终状态：{final.get('status')}")
        print(f"  辩论轮数：{final.get('debate_round')}")
        wo = final.get("workorder") or {}
        if wo.get("风险等级"):
            print(f"  工单风险：{wo['风险等级']} —— {wo.get('风险说明', '')}")
        else:
            print("  工单风险：正常")
        if final.get("followup_question"):
            print(f"  追问内容：{final['followup_question']}")
        hr()

        trace["final_status"] = final.get("status")
        trace["debate_round"] = final.get("debate_round")
        trace["risk_level"] = wo.get("风险等级") or "正常"
        trace["visit_order"] = [n["label"] for n in trace["nodes"]]
        if collect is not None:
            collect.append(trace)
    finally:
        orchestrator.settings.MAX_DEBATE_ROUNDS = original_max
        clear_token_tracker(correlation_id)


def _node_duration(correlation_id: str, last_by_node: dict):
    """读最近一个节点的累计耗时（取差值得到本次执行耗时）。

    节点可能被访问多次（辩论环），累计值会叠加，所以用差值。
    """
    tracker = get_token_tracker(correlation_id)
    summary = tracker.get_summary()
    return _diff_metric(summary, last_by_node, "duration_ms")


def _node_tokens(correlation_id: str, last_by_node: dict):
    tracker = get_token_tracker(correlation_id)
    summary = tracker.get_summary()
    return _diff_metric(summary, last_by_node, "total_tokens")


def _diff_metric(summary: dict, last_by_node: dict, field: str) -> float:
    """算出"相比上一次快照，各节点合计新增了多少"。"""
    by_node = summary.get("by_node") or {}
    total_now = sum(v.get(field, 0) for v in by_node.values())
    total_before = sum(v.get(field, 0) for v in (last_by_node or {}).values())
    # 把最新快照写回调用方的缓存（就地更新，调用方持有的是同一个 dict）
    last_by_node.clear()
    last_by_node.update({k: dict(v) for k, v in by_node.items()})
    return round(total_now - total_before, 1)


def main():
    args = sys.argv[1:]
    if "--list" in args:
        for k, (name, desc, _user_input, watch) in SCENARIOS.items():
            print(f"  {k:<14} {name} —— {desc}")
            print(f"  {'':<14} 看点：{watch}")
        return

    want_json = "--json" in args
    keys = [a for a in args if a in SCENARIOS] or list(SCENARIOS)
    unknown = [a for a in args if a not in SCENARIOS and not a.startswith("-")]
    if unknown:
        print(f"未知场景：{unknown}")
        print("可用场景：" + "、".join(SCENARIOS))
        return

    collected = []

    if not want_json:
        print("=" * W)
        print("  FlawScope 状态机离线演示（不联网、不花钱、不调模型）")
        print("  它跑的是真实的 orchestrator.app，只把调模型处换成了固定回答")
        print("  ⚠️ 耗时/token 由桩决定：token 恒为 0，耗时只反映节点分发开销，")
        print("     不代表真实性能——真实数字要靠 eval_test.py 联网跑。")
        print("=" * W)

    for k in keys:
        run_scenario(k, collect=collected)

    if want_json:
        out = Path(__file__).resolve().parent.parent / "trace_report.json"
        payload = {
            "note": "由 tools/trace_diagnosis.py --json 生成；模型已打桩，token 恒为 0，耗时为节点分发开销",
            "scenarios": collected,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已导出：{out}（{len(collected)} 个场景）")
    else:
        print("\n提示：对照 docs/PROJECT_GUIDE.md 第 4 章看，每条岔路都有解释。")
        print("      加 --json 可导出机器可读 trace（面试演示/回归对比用）。")


if __name__ == "__main__":
    main()

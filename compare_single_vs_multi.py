import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from agents import extract_fault_info, retrieve_evidence, agent_diagnose, evaluate_semantic
from orchestrator import run_diagnosis


def single_agent_diagnosis(fault_text: str) -> str:
    """单 Agent 流程：抽取 → 检索 → 一次诊断，无审核、无辩论、无校验"""
    fault_info = extract_fault_info(fault_text)

    query_parts = []
    if fault_info.get("设备类型"):
        query_parts.append(fault_info["设备类型"])
    if fault_info.get("报警代码") and str(fault_info.get("报警代码")).lower() not in ("null", "none"):
        query_parts.append(fault_info["报警代码"])
    if fault_info.get("故障现象"):
        query_parts.extend(fault_info["故障现象"])
    query = " ".join(query_parts) if query_parts else fault_text

    evidence = retrieve_evidence(query, k=3)
    diagnosis = agent_diagnose(evidence, json.dumps(fault_info, ensure_ascii=False), [])

    return diagnosis.get("根因判断", "")


def multi_agent_final_diagnosis(result: dict) -> tuple[str, int]:
    """多 Agent 流程的最终结论 + 辩论轮数"""
    rebuttal = result.get("rebuttal") or {}
    diagnosis = result.get("diagnosis") or {}
    if rebuttal.get("最终根因"):
        final = rebuttal["最终根因"]
    elif diagnosis.get("根因判断"):
        final = diagnosis["根因判断"]
    else:
        final = "无诊断结果"
    return final, result.get("debate_round", 0)


def exclusions_violated(text: str, excluded_keywords: list) -> list:
    """检查输出里仍残留哪些本应被排除的原因"""
    return [kw for kw in excluded_keywords if kw in text]


def is_unknown_response(text: str) -> bool:
    """判断是否诚实降级（说不知道，而非瞎编）"""
    return any(kw in text for kw in ("无法判断", "无法诊断", "无相关依据", "知识库无"))


def main():
    with open("test_cases.json", "r", encoding="utf-8") as f:
        cases = json.load(f)

    total = len(cases)
    single_pass = multi_pass = 0
    single_excl_bad = multi_excl_bad = 0
    single_honest = multi_honest = 0
    excl_cases = [c for c in cases if c.get("excluded_keywords")]
    unknown_cases = [c for c in cases if c.get("expect_unknown")]
    debate_corrected = []

    print("=" * 90)
    print("对比实验：单 Agent（一次诊断） vs 多 Agent（审核+辩论+复审）")
    print(f"测试集：{total} 案例（含排除条件 {len(excl_cases)} 例、知识库外 {len(unknown_cases)} 例对抗场景）")
    print("=" * 90)

    for i, case in enumerate(cases, 1):
        fault = case["fault_description"]
        expected = case["expected_diagnosis"]
        excl = case.get("excluded_keywords", [])
        is_unknown = case.get("expect_unknown", False)

        tag = ""
        if is_unknown:
            tag = "（对抗：知识库外）"
        elif excl:
            tag = "（对抗：排除条件）"

        print(f"\n[{i}/{total}] {case['id']}{tag}")
        print(f"故障：{fault.replace(chr(10), ' | ')[:70]}")
        if excl:
            print(f"应排除原因：{excl}")
        if is_unknown:
            print("标准行为：诚实降级（不应编造根因）")
        else:
            print(f"标准答案：{expected[:60]}")

        # ---- 单 Agent ----
        single_result = single_agent_diagnosis(fault)
        single_ok = evaluate_semantic(single_result, expected)
        if single_ok:
            single_pass += 1
        single_viol = exclusions_violated(single_result, excl)
        if single_viol:
            single_excl_bad += 1
        if is_unknown and is_unknown_response(single_result):
            single_honest += 1

        # ---- 多 Agent ----
        multi_result = run_diagnosis(fault)
        final, rounds = multi_agent_final_diagnosis(multi_result)
        multi_ok = evaluate_semantic(final, expected)
        if multi_ok:
            multi_pass += 1
        multi_viol = exclusions_violated(final, excl)
        if multi_viol:
            multi_excl_bad += 1
        if is_unknown and is_unknown_response(final):
            multi_honest += 1

        diag_root = (multi_result.get("diagnosis") or {}).get("根因判断", "")
        reb = multi_result.get("rebuttal") or {}
        if reb.get("最终根因") and diag_root and reb["最终根因"] != diag_root:
            debate_corrected.append(case["id"])

        status_s = "✓" if single_ok else "✗"
        status_m = "✓" if multi_ok else "✗"
        label_s = f" [残留:{single_viol or '无'}]" if excl else ""
        label_m = f" [残留:{multi_viol or '无'}][辩论{rounds}轮]" if excl else f" [辩论{rounds}轮]"
        print(f"  单Agent：{single_result[:52]} {status_s}{label_s}")
        print(f"  多Agent：{final[:52]} {status_m}{label_m}")

    print()
    print("=" * 90)
    print("▶ 汇总对比")
    print("-" * 90)
    print(f"① 诊断准确率       单Agent {single_pass}/{total} ({single_pass/total*100:.0f}%)  "
          f"多Agent {multi_pass}/{total} ({multi_pass/total*100:.0f}%)")
    print(f"② 排除条件遵守     单Agent 违规 {single_excl_bad}/{len(excl_cases)} 例  "
          f"多Agent 违规 {multi_excl_bad}/{len(excl_cases)} 例")
    print(f"③ 知识库外诚实降级 多Agent {multi_honest}/{len(unknown_cases)} 例  "
          f"单Agent {single_honest}/{len(unknown_cases)} 例")
    print(f"④ 辩论修正         多Agent 有 {len(set(debate_corrected))} 个案例经辩论改变最终根因")
    print("-" * 90)
    print("补充：多 Agent 独有能力（无法用准确率量化）")
    print("  · 证据溯源：每条结论标注'见资料X'，可回查")
    print("  · 结构审核：审核师独立把关，不通过不直接出单")
    print("  · 兜底降级：知识库不足/轮数用尽 → 明确标记待人工复核")
    print("  · 多模态+多轮追问：信息不足不硬猜")
    print("=" * 90)


if __name__ == "__main__":
    main()
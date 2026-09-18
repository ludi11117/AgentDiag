"""评估数据集的完整性检查（离线，不调 LLM）。

这套断言的目的：测试用例集本身是"考卷"，考卷出错会让评估结论完全失真。
三类以前踩过的坑，现在都固化成断言：

  1. 黄金根因在知识库里没有依据 —— 等于用错误答案去考系统，模型答对反而被判错。
     历史上改知识库时没人检查这一点。
  2. 用例 ID 重复 —— 报告与快照按 ID 索引，重复会让两条用例互相覆盖，统计静默失真。
  3. 排除条件与黄金根因自相矛盾 —— 例如把"轴承"列为排除项，黄金根因里又写"轴承损坏"，
     系统怎么做都是错的。

另外校验数据集仍有区分度所需的"难度配比"：带排除条件、无报警码、诚实降级三类样本
必须保持一定数量，否则指标会重新退化成"全都 100%"。
"""

import json
from pathlib import Path

import pytest

import eval_test

CASES_PATH = Path(__file__).resolve().parent.parent / "test_cases.json"


@pytest.fixture(scope="module")
def cases():
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def test_case_ids_are_unique(cases):
    ids = [c["id"] for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"用例 ID 重复：{sorted(dupes)}"


def test_every_expected_root_cause_is_grounded_in_knowledge_base(cases):
    """黄金根因必须能在知识库里找到依据，否则是在用错误答案考核系统。"""
    ungrounded = []
    for c in cases:
        for expected in eval_test.extract_expected_root_causes(c):
            if not eval_test._grounded_in_kb(expected):
                ungrounded.append(f"{c['id']}: {expected}")
    assert not ungrounded, "以下黄金根因在知识库中无依据：\n  " + "\n  ".join(ungrounded)


def test_expected_root_causes_do_not_contradict_excluded_keywords(cases):
    """排除条件不得与黄金根因冲突：被排除的词不能出现在期望答案里。"""
    conflicts = []
    for c in cases:
        for expected in eval_test.extract_expected_root_causes(c):
            for kw in c.get("excluded_keywords", []):
                if kw and kw in expected:
                    conflicts.append(f"{c['id']}: 排除关键词「{kw}」出现在黄金根因「{expected}」中")
    assert not conflicts, "用例自相矛盾：\n  " + "\n  ".join(conflicts)


def test_dataset_keeps_discriminating_cases(cases):
    """数据集必须保留足够多的"难题"。

    只有报警码直查型用例时，指标会退化为 100%（2026-09-13 的报告即如此）。
    这里给三类难度样本设下限，防止后续精简用例时把区分度删掉。
    """
    excluded = [c["id"] for c in cases if c.get("excluded_keywords")]
    no_code = [c["id"] for c in cases if "报警代码" not in c["fault_description"]]
    unknown = [c["id"] for c in cases if c.get("expect_unknown")]

    assert len(excluded) >= 8, f"带排除条件的用例过少：{len(excluded)}（{excluded}）"
    assert len(no_code) >= 5, f"无报警码（抗模糊）用例过少：{len(no_code)}（{no_code}）"
    assert len(unknown) >= 3, f"诚实降级用例过少：{len(unknown)}（{unknown}）"


def test_dataset_covers_multiple_equipment_types(cases):
    """设备类型要有广度，否则检索永远命中同一段，测不出排序能力。"""
    devices = set()
    for c in cases:
        for line in c["fault_description"].splitlines():
            if line.startswith("设备类型："):
                devices.add(line.replace("设备类型：", "").strip())
    assert len(devices) >= 10, f"设备类型覆盖不足：{len(devices)} 种（{sorted(devices)}）"


# ========== 向量库切分：文件头不得参与检索 ==========
# 文件头是给人看的元信息（标题、来源说明、免责声明）。把它一起切分进向量库后，
# 它会变成 200 字左右的碎片参与检索，而检索名额只有 RETRIEVAL_K=3 个——
# 实测（2026-09-18）「# FlawScope 知识库…」「---」「> 而这正是本项目…」这类碎片
# 会挤掉真正的故障条目：三个查询里各有 1–2 个名额被这样浪费。

def test_strip_preamble_removes_file_header_only():
    """剥离只砍文件头，设备章节正文必须逐字符保留。"""
    from build_knowledge_base import strip_preamble

    text = (
        "# FlawScope 知识库 —— 维修经验整理\n\n"
        "> **来源说明（重要）**：本文件是维修经验整理。\n\n"
        "---\n\n"
        "【数控机床主轴电机常见故障与排查】\n\n"
        "一、主轴电机报警代码E-203\n故障现象：主轴转速不稳定。\n"
    )
    body = strip_preamble(text)

    assert body.startswith("【数控机床主轴电机常见故障与排查】"), "剥离后应从第一个设备章节开始"
    # 文件头内容一个都不该留下
    assert "来源说明（重要）" not in body
    assert "# FlawScope" not in body
    # 正文一个字都不能少
    assert "一、主轴电机报警代码E-203" in body
    assert "故障现象：主轴转速不稳定。" in body


def test_strip_preamble_is_noop_without_section_header():
    """没有设备章节标题时原样返回——宁可检索到噪声，也不能静默丢内容。"""
    from build_knowledge_base import strip_preamble

    text = "一、某种故障\n故障现象：xxx。\n"
    assert strip_preamble(text) == text


def test_knowledge_base_has_preamble_to_strip():
    """知识库当前确实带文件头——否则上一条守卫是空转。"""
    from build_knowledge_base import KB_PATH, strip_preamble

    text = KB_PATH.read_text(encoding="utf-8")
    assert len(strip_preamble(text)) < len(text), "知识库没有文件头，剥离逻辑无从验证"
    assert text.startswith("#"), "文件头不见了？请确认来源说明没有被误删"

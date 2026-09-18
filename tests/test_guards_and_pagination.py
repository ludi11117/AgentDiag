"""针对"本轮修复但此前无覆盖"的缺陷的回归测试。

全部离线运行：不调用 LLM、不联网、不触碰真实数据库。

覆盖点：
  - /records 的 total 语义（必须是匹配总数，而不是被 LIMIT 截断后的行数）
  - 排除映射的作用域收窄（未命中必须返回空，不能跨设备误伤）
  - 报警代码归一化（E-203 / E203 / e 203 视为同一个代码，避免误降级）
  - evaluate_semantic 的严格口径（非预期输出不能算作"一致"）
  - 成本提示（价格表未覆盖的备件必须显式告知，不能静默不计费）
  - BM25 索引的并发构建（多线程下只能构建一次）
  - TokenTracker 快照的隔离性（后续调用不能改写已产出的快照）
  - 历史记录里的 correlation_id 往返
"""

import threading
import time

import pytest

import agents as agents_module
import orchestrator
from logging_config import TokenTracker

# isolated_db 夹具已提到 tests/conftest.py，多个测试文件共用一份实现


# ========== /records 的 total 必须是不受 LIMIT 影响的匹配总数 ==========

def test_count_records_is_not_capped_by_limit(isolated_db):
    """此前 api.py 用 len(get_records(...)) 当 total，分页时 total 永远等于 limit，
    调用方无法判断"还有没有更多"。"""
    for i in range(5):
        isolated_db.save_diagnosis_record(f"故障{i}", {"status": "done"}, {})

    assert len(isolated_db.get_records(limit=2)) == 2      # 列表确实被截断
    assert isolated_db.count_records() == 5                # 但总数必须是真实的 5


def test_count_records_respects_same_filters_as_get_records(isolated_db):
    """总数与列表必须用同一套过滤条件，否则会出现"列表 1 条、总数 5 条"。"""
    isolated_db.save_diagnosis_record("液压泵异响", {"status": "done"}, {})
    isolated_db.save_diagnosis_record("主轴异响", {"status": "insufficient_knowledge"}, {})

    assert isolated_db.count_records(keyword="液压") == 1
    assert isolated_db.count_records(status="done") == 1
    assert isolated_db.count_records(keyword="液压", status="done") == 1
    assert isolated_db.count_records(keyword="液压", status="insufficient_knowledge") == 0


def test_records_endpoint_reports_true_total(isolated_db):
    """/records 端到端：limit=2 时 total 仍是 5。

    注意 offset 必须显式传：直接调用端点函数会绕过 FastAPI 的参数解析，
    不传的话拿到的是 Query 对象本身而不是默认值 0。HTTP 契约本身由
    test_pagination_and_export.py 里的 OpenAPI schema 测试来守。
    """
    for i in range(5):
        isolated_db.save_diagnosis_record(f"故障{i}", {"status": "done"}, {})

    from api import records as records_endpoint

    payload = records_endpoint(keyword="", status="", limit=2, offset=0, _=None)
    assert payload["total"] == 5
    assert len(payload["records"]) == 2


# ========== 排除映射：未命中必须返回空，不能放开成全量 ==========

KB_ENTRIES = [("主轴电机", "轴承损坏"), ("液压系统", "溢流阀卡滞")]


def test_relevant_scope_returns_empty_when_nothing_matches():
    """给了设备/代码却一条都没命中 → 说明本轮资料里没有这个设备。

    此时若回退成全量，排除映射会拿 A 设备的排除条件去删 B 设备的原因条目。
    """
    assert agents_module._relevant_scope(KB_ENTRIES, "数控机床", "E-999") == []


def test_relevant_scope_narrows_to_matching_entries():
    assert agents_module._relevant_scope(KB_ENTRIES, "主轴电机", "") == [0]
    assert agents_module._relevant_scope(KB_ENTRIES, "液压系统", "") == [1]


def test_relevant_scope_keeps_full_range_without_device_or_code():
    """没有任何可依据的设备/代码时不做收窄，全量交给映射器判断。"""
    assert agents_module._relevant_scope(KB_ENTRIES, "", "") == [0, 1]


def test_map_excluded_causes_skips_mapping_when_scope_is_empty(monkeypatch):
    """作用域为空时不应发起 LLM 调用——跨设备猜测是明确要避免的行为。"""
    def _should_not_run(*a, **kw):
        raise AssertionError("作用域为空时不该调用模型")

    monkeypatch.setattr(agents_module, "safe_llm_invoke", _should_not_run)
    assert agents_module.map_excluded_causes(["轴承没问题"], KB_ENTRIES, []) == []


# ========== 报警代码归一化：写法差异不该被判成"资料里没有" ==========

@pytest.mark.parametrize("code, evidence, expected", [
    ("E-203", "报警 E203 主轴异常", True),
    ("E203", "报警 E-203 主轴异常", True),
    ("e 203", "报警 E_203 主轴异常", True),
    ("E-203", "报警 E-101 电源异常", False),
])
def test_equipment_guard_normalizes_alarm_code_format(code, evidence, expected):
    """现场写法不统一（E-203 / E203 / e 203 / E_203），精确子串比对会误判成无依据，
    触发本不该发生的降级（README 指标⑦ 误降级率）。"""
    assert agents_module.is_equipment_in_evidence({"设备类型": "", "报警代码": code}, evidence) is expected


def test_equipment_guard_ignores_too_short_alarm_code():
    """过短的代码归一化后几乎能命中任意文本，此时不做代码级判定。"""
    assert agents_module.is_equipment_in_evidence({"设备类型": "", "报警代码": "1"}, "任意资料") is True


# ========== evaluate_semantic：必须明确说"一致"才算命中 ==========

@pytest.mark.parametrize("verdict, expected", [
    ("一致", True),
    ("不一致", False),
    ("无法判断", False),
    ("不确定是否一致", False),
])
def test_evaluate_semantic_requires_explicit_agreement(monkeypatch, verdict, expected):
    """此前是 `"不一致" not in content`，任何非预期输出（模型跑偏、截断）都会
    被算作"一致"，等于给评估指标注水。"""
    monkeypatch.setattr(agents_module, "safe_llm_invoke", lambda *a, **kw: verdict)
    assert agents_module.evaluate_semantic("系统诊断", "标准答案") is expected


def test_evaluate_semantic_returns_false_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(agents_module, "safe_llm_invoke", lambda *a, **kw: None)
    assert agents_module.evaluate_semantic("系统诊断", "标准答案") is False


# ========== 成本提示：未覆盖的备件必须显式告知 ==========

def test_agent_cost_flags_unpriced_parts(monkeypatch):
    """价格表没覆盖的备件不计费是对的，但必须显式提示，
    否则用户会以为报价是完整的。"""
    monkeypatch.setattr(
        agents_module, "invoke_and_validate",
        lambda *a, **kw: agents_module.CostExtractOutput(备件清单=["主轴轴承", "外星轴承"], 预计工时=1)
    )
    result = agents_module.agent_cost({"根因判断": "轴承损坏"}, {})

    assert result["成本明细"]["备件费用"] == 850          # 只有已知备件计费
    assert result["成本明细"]["未知备件"] == ["外星轴承"]
    assert "外星轴承" in result["计费提示"]


def test_agent_cost_has_empty_hint_when_all_parts_priced(monkeypatch):
    monkeypatch.setattr(
        agents_module, "invoke_and_validate",
        lambda *a, **kw: agents_module.CostExtractOutput(备件清单=["主轴轴承"], 预计工时=2)
    )
    result = agents_module.agent_cost({"根因判断": "轴承损坏"}, {})
    assert result["计费提示"] == ""


# ========== BM25 索引：并发下只构建一次 ==========

def test_bm25_index_is_built_only_once_under_concurrency(monkeypatch):
    """构建索引要遍历整个知识库做 jieba 分词，代价很高。

    Streamlit 多会话 + FastAPI 线程池会并发进入首次检索，没有锁的话
    同一份索引会被反复重建。这里用 sleep 放大竞争窗口，
    无锁实现必然出现多次 db.get()。
    """
    calls = {"get": 0}
    docs = [f"资料{i}：主轴轴承损坏" for i in range(20)]

    class _SlowStubChroma:
        def get(self):
            calls["get"] += 1
            time.sleep(0.02)
            return {"documents": docs}

    monkeypatch.setattr(agents_module, "get_db", lambda: _SlowStubChroma())
    monkeypatch.setattr(agents_module, "_bm25_initialized", False)

    threads = [threading.Thread(target=agents_module._init_bm25) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["get"] == 1, "并发下 BM25 索引被重复构建"


# ========== 懒加载单例：并发下只能构造一次 ==========

def _hammer(fn, threads: int = 8):
    """让 N 个线程尽量同时冲进 fn，制造"首次构造"的重叠窗口。"""
    barrier = threading.Barrier(threads)

    def worker():
        barrier.wait()
        fn()

    pool = [threading.Thread(target=worker) for _ in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()


def test_get_llm_is_built_only_once_under_concurrency(monkeypatch):
    """get_llm 此前是裸的 `if _llm is None: _llm = ChatOpenAI(...)`。

    Streamlit 多会话 + FastAPI 线程池会同时进入首次调用，几个线程都读到 None，
    于是同一个客户端被构造多次。BM25 索引与 TokenTracker 早就为此加了锁，
    这几个 getter 是漏网的。
    """
    built = []

    class _SlowChatOpenAI:
        def __init__(self, **kwargs):
            time.sleep(0.05)          # 放大"读到 None"与"完成赋值"之间的窗口
            built.append(kwargs.get("model"))

    monkeypatch.setattr(agents_module, "ChatOpenAI", _SlowChatOpenAI)
    monkeypatch.setattr(agents_module, "_llm", None)

    _hammer(agents_module.get_llm)

    assert built == [agents_module.settings.DIAGNOSIS_MODEL], "并发下主 LLM 被重复构造"


def test_get_vision_llm_is_built_only_once_under_concurrency(monkeypatch):
    built = []

    class _SlowChatOpenAI:
        def __init__(self, **kwargs):
            time.sleep(0.05)
            built.append(kwargs.get("model"))

    monkeypatch.setattr(agents_module, "ChatOpenAI", _SlowChatOpenAI)
    monkeypatch.setattr(agents_module, "_vision_llm", None)

    _hammer(agents_module.get_vision_llm)

    assert built == [agents_module.settings.VISION_MODEL], "并发下视觉模型被重复构造"


def test_get_embeddings_is_built_only_once_under_concurrency(monkeypatch):
    built = []

    class _SlowEmbeddings:
        def __init__(self, **kwargs):
            time.sleep(0.05)
            built.append(kwargs.get("model"))

    monkeypatch.setattr(agents_module, "OpenAIEmbeddings", _SlowEmbeddings)
    monkeypatch.setattr(agents_module, "_embeddings", None)

    _hammer(agents_module.get_embeddings)

    assert built == [agents_module.settings.EMBEDDING_MODEL], "并发下嵌入模型被重复构造"


def test_get_db_is_built_only_once_under_concurrency(monkeypatch):
    """Chroma 是最不能重复构造的一个：同一个 persist 目录被开出多个
    PersistentClient 会争抢底层 SQLite 锁。"""
    built = []

    class _SlowChroma:
        def __init__(self, **kwargs):
            time.sleep(0.05)
            built.append(kwargs.get("persist_directory"))

    monkeypatch.setattr(agents_module, "Chroma", _SlowChroma)
    monkeypatch.setattr(agents_module, "get_embeddings", lambda: object())
    monkeypatch.setattr(agents_module, "_db", None)

    _hammer(agents_module.get_db)

    assert len(built) == 1, "并发下向量库客户端被重复构造"


def test_singleton_lock_is_reentrant():
    """get_db 会在**持锁状态下**调用 get_embeddings()，所以 _singleton_lock
    必须可重入。用普通 Lock 的话，同一个线程第二次 acquire 会把自己锁死——
    表现为首次调用 get_db() 的请求永久挂起，而不是报错。
    """
    lock = agents_module._singleton_lock
    with lock:
        acquired = lock.acquire(timeout=1)
        assert acquired, "_singleton_lock 不可重入：get_db 会在自己线程里自锁死"
        lock.release()


# ========== TokenTracker 快照必须与后续调用隔离 ==========

def test_token_tracker_summary_is_isolated_from_later_usage():
    """get_summary() 是浅拷贝的话，调用方拿到的 by_node 与 tracker 内部是同一个对象，
    后续再发生的 LLM 调用会改写这份"历史快照"，导致入库的统计与当时实际不符。"""
    tracker = TokenTracker("cid-snapshot")
    tracker.start_node("diagnose")
    tracker.add_usage(100, 20)

    snapshot = tracker.get_summary()

    tracker.add_usage(999, 999)          # 快照产出之后又发生了调用

    assert snapshot["total_tokens"] == 120
    assert snapshot["by_node"]["diagnose"]["total_tokens"] == 120


# ========== 历史记录里的 correlation_id 往返 ==========

def test_save_and_read_back_correlation_id(isolated_db):
    """correlation_id 是"全链路追踪"的钥匙：日志里能用它串起一轮诊断，
    历史记录里也必须存下来，否则事后无法把某条记录对回它的日志。"""
    isolated_db.save_diagnosis_record(
        "主轴异响",
        {"status": "done", "correlation_id": "abc12345"},
        {},
    )
    assert isolated_db.get_records()[0]["correlation_id"] == "abc12345"


# ========== 工单生成失败时，不该把降级原因改写成"模型服务异常" ==========

def test_workorder_failure_preserves_knowledge_gap_status(monkeypatch):
    """知识库无依据 + 工单生成也失败时，状态必须保留 insufficient_knowledge。

    一律覆盖成 llm_failed 会把"知识库没覆盖该设备"说成"模型服务异常"，
    用户会照着错误的原因去排查（该补知识库，却去查模型服务）。
    """
    monkeypatch.setattr(orchestrator, "agent_workorder", lambda *a, **kw: {})
    state = {
        "correlation_id": "cid-wo-prior",
        "diagnosis": {"报警代码": "N/A", "根因判断": "知识库无相关依据，无法诊断",
                      "依据": "无", "排查建议": []},
        "review": {}, "cost": {}, "rebuttal": {}, "final_review": {},
        "debate_round": 0, "max_debate_rounds": 3,
        "status": "insufficient_knowledge",
    }
    result = orchestrator.workorder_node(state)

    assert result["status"] == "insufficient_knowledge"
    assert result["workorder"]["风险等级"] == "待人工确认（模型服务异常）"


def test_workorder_failure_reports_llm_failed_when_no_prior_degradation(monkeypatch):
    """非降级路径下工单生成失败，才应报 llm_failed。"""
    monkeypatch.setattr(orchestrator, "agent_workorder", lambda *a, **kw: {})
    state = {
        "correlation_id": "cid-wo-normal",
        "diagnosis": {"报警代码": "E-203", "根因判断": "主轴轴承损坏", "依据": "资料1", "排查建议": []},
        "review": {"审核意见": "通过"}, "cost": {}, "rebuttal": {}, "final_review": {},
        "debate_round": 0, "max_debate_rounds": 3,
        "status": "costed",
    }
    assert orchestrator.workorder_node(state)["status"] == "llm_failed"


# ========== 幻觉检测的严格口径（比对检索片段，而非全库子串）==========

_EVIDENCE_H110 = """【资料1】
二、液压系统报警代码H-110
故障现象：系统压力完全建立不起来，压力表指针接近零位，油泵有异响。
可能原因：
1. 液压泵吸油口过滤器堵塞，产生吸空现象。"""


def test_grounding_strict_scope_rejects_cause_from_other_section():
    """严格口径下，检索只命中液压段时，引用主轴段的根因必须判为幻觉。

    这是此前幻觉率虚高的根因：原实现只跟整份知识库做子串匹配，
    只要那句话在库里的**任何位置**出现就算接地——库越大、答案越"好猜"，
    指标反而越漂亮。改用检索片段后，"引用了没检索到的资料"才会被抓住。
    """
    import eval_test

    assert eval_test._grounded_in_evidence("液压泵吸油口过滤器堵塞，产生吸空现象", _EVIDENCE_H110) is True
    assert eval_test._grounded_in_evidence("主轴轴承损坏", _EVIDENCE_H110) is False

    hallucinated, fake = eval_test.is_hallucinated(
        "液压泵吸油口过滤器堵塞；主轴轴承损坏", _EVIDENCE_H110
    )
    assert hallucinated is True
    assert fake == ["主轴轴承损坏"]


def test_grounding_loose_scope_is_more_permissive_than_strict():
    """同一条越界根因，宽松口径（全库）放行、严格口径（检索片段）拦下。

    断言两者**结论不同**，否则测试只是装饰——若某次重构把两个口径悄悄合并，
    这条会立刻失败。
    """
    import eval_test

    root = "液压泵吸油口过滤器堵塞；主轴轴承损坏"
    assert eval_test.is_hallucinated(root, _EVIDENCE_H110)[0] is True
    assert eval_test.is_hallucinated(root)[0] is False


def test_grounding_treats_no_evidence_placeholder_as_ungrounded():
    """检索明确返回"无相关依据"占位符时，任何根因都不算接地。"""
    import eval_test

    assert eval_test._grounded_in_evidence("液压泵磨损", "【知识库无相关依据】") is False


def test_evaluate_case_passes_evidence_into_hallucination_check(monkeypatch):
    """保证 evaluate_case 把检索片段喂给幻觉检测，而不是退回全库口径。


    上面三条测的是函数本身，改坏了函数它们会失败；但**漏传 evidence** 这种
    接线错误它们照样全绿——指标会静默退回宽松口径、幻觉率重新虚高。
    这条直接盯住调用点：只给一个"检索片段之外"的根因，严格口径必须报幻觉。
    """
    import eval_test

    fake_result = {
        "diagnosis": {"报警代码": "H-110", "根因判断": "主轴轴承损坏", "依据": "资料1", "排查建议": []},
        "rebuttal": {},
        "evidence": _EVIDENCE_H110,
        "debate_round": 0,
        "token_usage": {},
        "correlation_id": "cid-grounding",
    }
    monkeypatch.setattr(eval_test, "run_diagnosis", lambda *a, **kw: fake_result)

    class _Args:
        judge_model = "stub"
        skip_judge = True
        no_debate_analysis = True

    case = {"id": "TG001", "fault_description": "液压系统 H-110 压力建立不起来",
            "expected_diagnosis": "液压泵吸油口过滤器堵塞", "excluded_keywords": []}
    record = eval_test.evaluate_case(case, _Args())

    assert record["evidence"] == _EVIDENCE_H110
    assert record["hallucinated"] is True
    assert record["hallucinated_causes"] == ["主轴轴承损坏"]


# ========== 设备类型护栏必须容忍同义不同名 ==========

_EV_COMPRESSOR = """【资料2】
二、空压机报警代码A-203
故障现象：机组剧烈振动，运行电流波动大。
可能原因：
1. 主机轴承磨损，转子间隙增大。"""

_EV_SPINDLE = """【资料1】
一、主轴电机报警代码E-203
故障现象：主轴转速不稳定，伴有异常噪音。"""


@pytest.mark.parametrize("device,evidence,note", [
    ("空气压缩机", _EV_COMPRESSOR, "知识库写空压机、用户说空气压缩机"),
    ("空压机", _EV_COMPRESSOR, "完全同名"),
    ("螺杆式空气压缩机", _EV_COMPRESSOR, "带型号前缀"),
])
def test_equipment_guard_accepts_synonyms(device, evidence, note):
    """同义不同名不得被误判为"无依据"。

    此前是裸的精确子串比对：用户说"空气压缩机"、知识库标题写"空压机"，
    `"空气压缩机" in evidence` 为 False，一个本来能答的案例被直接降级。
    这个缺陷在知识库只有 3 个主题时测不出来——那时"空压机"只作为对抗案例出现，
    误降级和正确的降级看起来一模一样。
    """
    assert agents_module.is_equipment_in_evidence({"设备类型": device}, evidence) is True, note


@pytest.mark.parametrize("device,evidence,note", [
    ("注塑机", _EV_SPINDLE, "注塑机不在主轴电机资料里"),
    ("龙门加工中心", _EV_SPINDLE, "龙门加工中心不在主轴电机资料里"),
    ("离心泵", _EV_COMPRESSOR, "离心泵不在空压机资料里"),
])
def test_equipment_guard_still_blocks_genuine_mismatch(device, evidence, note):
    """放宽同义词不能把护栏放穿：设备确实不在资料里时必须仍然拦下。

    与上一条配对——只测"放行"会让人把护栏越改越松，最后退化成恒返回 True。
    """
    assert agents_module.is_equipment_in_evidence({"设备类型": device}, evidence) is False, note


def test_equipment_guard_rejects_when_no_evidence_placeholder():
    """检索明确说无依据时，护栏必须拦下，不受同义词展开影响。"""
    info = {"设备类型": "空压机", "报警代码": "A-203"}
    assert agents_module.is_equipment_in_evidence(info, "【知识库无相关依据】") is False


# ========== 排除条件不得被静默丢弃 ==========

_TC018_ENTRIES = [
    ("变频器报警代码F-014", "电机绕组对地绝缘破损。"),
    ("变频器报警代码F-014", "动力电缆在桥架转弯处磨损露出导体。"),
    ("变频器报警代码F-014", "变频器内部电流互感器故障造成误报。"),
]


def test_deterministic_exclusion_maps_every_exclusion_item():
    """每条排除项都必须各自映射到一条原因，不能整条被漏掉。

    TC018 实测缺陷：用户说了两条排除条件（电机绕组 / 电缆护套），
    但只映射出 [0]，第二条对应的"动力电缆磨损"留在根因里，
    等于把用户刚验证过没问题的原因又当成故障原因写回去。
    """
    hits = agents_module._deterministic_exclusion_hits(
        ["电机绕组对地绝缘测量正常", "电缆护套完好"],
        _TC018_ENTRIES,
        [0, 1, 2],
    )
    assert hits == [0, 1]


def test_exclusion_detection_survives_llm_partial_answer(monkeypatch):
    """LLM 只答对一部分时，确定性匹配必须补上剩下的——不能被短路掉。

    原实现写作 `if not idx:`：只要 LLM 返回了任意编号，确定性匹配整段跳过。
    语义变成"LLM 只要答对一部分，剩下就没人管了"。

    ⚠️ 这条必须**驱动 map_excluded_causes 本身**并桩掉 LLM，
    不能只断言"并集算术"——那样即使把并集改回 `if not idx:`，
    测试照样全绿（写过一版就是这样，被退化验证抓出来的）。
    """
    import agents as agents_module

    entries = [
        ("变频器报警代码F-014", "电机绕组对地绝缘破损。"),
        ("变频器报警代码F-014", "动力电缆在桥架转弯处磨损露出导体。"),
        ("变频器报警代码F-014", "变频器内部电流互感器故障造成误报。"),
    ]

    # 桩掉 LLM：只返回编号 1（即条目 [0]），模拟"答对一半"。
    # invoke_and_parse_json 才是真正发起调用的那层，桩它既不改逻辑也不联网。
    monkeypatch.setattr(
        agents_module, "invoke_and_parse_json",
        lambda *a, **kw: {"排除编号": [1]},
    )
    agents_module._exclusion_cache.clear()

    idx = agents_module.map_excluded_causes(
        ["电机绕组对地绝缘测量正常", "电缆护套完好"], entries, scope=[0, 1, 2]
    )
    # LLM 只给了 [0]；确定性匹配补上 [1]；并集才是正确结果
    assert idx == [0, 1], f"LLM 漏掉的排除项未被补救：{idx}"


def test_exclusion_cache_does_not_leak_between_calls(monkeypatch):
    """缓存键包含排除条件，不同输入不得互相污染。"""
    import agents as agents_module

    entries = [("变频器报警代码F-014", "动力电缆在桥架转弯处磨损露出导体。")]
    monkeypatch.setattr(
        agents_module, "invoke_and_parse_json",
        lambda *a, **kw: {"排除编号": []},
    )
    agents_module._exclusion_cache.clear()

    hit = agents_module.map_excluded_causes(["电缆护套完好"], entries, scope=[0])
    miss = agents_module.map_excluded_causes(["液压油位正常"], entries, scope=[0])
    assert hit == [0]
    assert miss == []


def test_exclusion_stopwords_do_not_dilute_match():
    """"正常/完好/测量"这类词不该参与匹配——它们不指向任何原因。

    这些词会让排除描述的 token 集合变大，稀释真正有指向性的词（如"电缆"）。
    """
    assert "正常" not in agents_module._exclusion_tokens("液压油位正常")
    assert "完好" not in agents_module._exclusion_tokens("电缆护套完好")
    assert "测量" not in agents_module._exclusion_tokens("绝缘测量正常")
    # 有指向性的词必须保留（jieba 把"液压油位正常"切成 液压油/位/正常）
    assert "电缆" in agents_module._exclusion_tokens("电缆护套完好")
    assert "液压油" in agents_module._exclusion_tokens("液压油位正常")
    # "冷却风扇运转正常"应保留到"冷却""风扇"，并被"正常"剔除后仍可匹配
    tokens = agents_module._exclusion_tokens("冷却风扇运转正常")
    assert "正常" not in tokens and "冷却" in tokens


def test_single_overlapping_token_is_still_a_match():
    """"电缆护套完好"与"动力电缆…磨损"只共用 1 个 token，也必须判为命中。

    排除描述与原因条目本来就常常只重合一个词，这是自然语言的常态。
    按比例卡阈值会让这类排除全部失效——而漏排除正是要修的问题。
    """
    hits = agents_module._deterministic_exclusion_hits(
        ["电缆护套完好"], _TC018_ENTRIES, [0, 1, 2]
    )
    assert hits == [1]


def test_exclusion_mapping_only_searches_within_scope():
    """确定性匹配必须尊重 scope，不能跨设备误伤。"""
    hits = agents_module._deterministic_exclusion_hits(
        ["电缆护套完好"], _TC018_ENTRIES, [0]   # 把目标条目排除在范围外
    )
    assert hits == []


# ========== 辩论阶段不得静默丢弃候选根因 ==========
#
# TC021 实测缺陷：初诊给出 3 条候选，辩论后只剩 2 条，第 3 条无声消失——
# 表现为**核心一致率满分、全覆盖率掉分**。初诊提示词要求"有几项写几项、
# 不得自行取舍"，但辩论提示词没有等价约束，且辩论会换查询重新检索。
# 约束漂移，所以用确定性代码兜住，而不是再加一句提示词。

def test_restore_dropped_candidates_brings_back_missing_cause():
    """TC021 场景：初诊 3 条候选，辩论后只剩 2 条，第 3 条必须被补回。"""
    initial = "原因1：密封件老化开裂；原因2：装配时密封面有杂质；原因3：轴颈磨损导致间隙超标"
    final = "原因1：密封件老化开裂；原因2：装配时密封面有杂质"
    out = agents_module.restore_dropped_candidates(initial, final, excluded_causes=[])
    assert "轴颈磨损导致间隙超标" in out, f"被丢弃的候选未补回：{out}"
    # 原有的两条不能被弄丢，也不能重复
    assert out.count("密封件老化开裂") == 1
    assert out.count("装配时密封面有杂质") == 1


def test_restore_dropped_candidates_leaves_no_loss_text_unchanged():
    """没有丢候选时，输出必须逐字符等于输入——护栏不得顺手改写正常结论。"""
    text = "原因1：密封件老化开裂；原因2：装配时密封面有杂质"
    assert agents_module.restore_dropped_candidates(text, text, excluded_causes=[]) == text


@pytest.mark.parametrize("degraded", [
    "知识库无相关依据，无法诊断",
    "无法判断该故障的根因，建议人工复核",
    "模型调用失败，未能完成诊断",
    "输出校验未能完成，无法给出结论",
])
def test_restore_dropped_candidates_never_rewrites_degradation(degraded):
    """降级结论一律不得改写。

    ⚠️ 这是本护栏第一版的真实 bug：判定写在"拆分候选"之后，
    而降级文句含全角逗号，拆完被切碎，逐片判断全部漏掉——
    结果把"知识库无相关依据，无法诊断"改成了
    "知识库无相关依据; 无法诊断; 吸入管路漏气或阀失效"，
    等于给每一张降级工单都编造了根因，直接打穿诚实降级防线。
    所以判定必须在拆分**之前**做，这条测试就是钉住这个顺序。
    """
    initial = "原因1：密封件老化开裂；原因2：装配时密封面有杂质"
    out = agents_module.restore_dropped_candidates(initial, degraded, excluded_causes=[])
    assert out == degraded, f"降级结论被护栏改写：{out!r}"


def test_restore_dropped_candidates_feeds_degradation_as_initial_too():
    """初诊就是降级文句时同样不得改写（判定两处都要有）。"""
    degraded = "知识库无相关依据，无法诊断"
    out = agents_module.restore_dropped_candidates(degraded, degraded, excluded_causes=[])
    assert out == degraded


def test_restore_dropped_candidates_skips_user_excluded_causes():
    """用户已排除的原因不得被补回来——否则等于让用户白排除一次。"""
    initial = "原因1：密封件老化开裂；原因2：轴颈磨损导致间隙超标"
    final = "原因1：密封件老化开裂"
    out = agents_module.restore_dropped_candidates(
        initial, final, excluded_causes=["轴颈磨损"]
    )
    assert "轴颈磨损" not in out, f"已排除的原因被补回：{out}"
    assert "密封件老化开裂" in out


def test_restore_dropped_candidates_treats_containment_as_covered():
    """一方包含另一方视为仍被覆盖，不算丢弃——避免把同一原因换个说法又加一遍。"""
    initial = "原因1：密封件老化开裂失效"
    final = "原因1：密封件老化开裂"
    out = agents_module.restore_dropped_candidates(initial, final, excluded_causes=[])
    assert out == final, f"语义重复被误判为丢弃：{out}"


def test_restore_dropped_candidates_handles_empty_inputs():
    """空输入不得抛异常，也不得凭空造出内容。"""
    assert agents_module.restore_dropped_candidates("", "原因1：X") == "原因1：X"
    assert agents_module.restore_dropped_candidates("原因1：X", "") == ""
    assert agents_module.restore_dropped_candidates("", "") == ""


def test_agent_rebuttal_guard_is_wired_in(monkeypatch):
    """护栏必须真的接在 agent_rebuttal 上，不能只是定义了一个没人调的函数。

    ⚠️ 与排除映射那条同一个坑：断言"函数自己算得对"是**测不到接线**的，
    必须驱动 agent_rebuttal 本身，桩掉模型调用。桩的是 invoke_and_validate
    （agent_rebuttal 真正发起调用的那层），既不联网也不改业务逻辑。
    """
    class _FakeRebuttal:
        def model_dump(self):
            return {"最终根因": "原因1：密封件老化开裂", "辩论意见": "维持首条"}

    monkeypatch.setattr(
        agents_module, "invoke_and_validate", lambda *a, **kw: _FakeRebuttal()
    )

    diagnosis = {
        "根因判断": "原因1：密封件老化开裂；原因2：轴颈磨损导致间隙超标",
        "置信度": 0.8,
    }
    out = agents_module.agent_rebuttal(diagnosis, {"结论": "通过"}, "证据文本", "{}")
    assert "轴颈磨损导致间隙超标" in out.get("最终根因", ""), \
        f"护栏没接上 agent_rebuttal：{out.get('最终根因')!r}"


def test_agent_rebuttal_does_not_rewrite_degraded_verdict(monkeypatch):
    """接在真实链路上时，降级结论同样不得被改写（端到端钉住判定顺序）。"""
    class _FakeRebuttal:
        def model_dump(self):
            return {"最终根因": "知识库无相关依据，无法诊断"}

    monkeypatch.setattr(
        agents_module, "invoke_and_validate", lambda *a, **kw: _FakeRebuttal()
    )
    diagnosis = {"根因判断": "原因1：密封件老化开裂；原因2：轴颈磨损导致间隙超标"}
    out = agents_module.agent_rebuttal(diagnosis, {"结论": "通过"}, "证据文本", "{}")
    assert out["最终根因"] == "知识库无相关依据，无法诊断", \
        f"降级结论在辩论链路上被改写：{out['最终根因']!r}"


def test_degraded_markers_stay_in_sync_with_orchestrator():
    """降级标记的两份副本必须一致——不同步会让"降级不得改写"静默失效。

    标记只在"某种降级文句恰好走到辩论路径上"时才暴露，属于典型静默失效。
    orchestrator 是正本（它反向依赖本模块，所以 agents 不能直接 import）。
    """
    missing = [m for m in orchestrator.DEGRADED_MARKERS if m not in agents_module._DEGRADED_MARKERS]
    assert not missing, f"agents 侧缺少降级标记：{missing}"



# ========== 辩论越界护栏（drop_out_of_scope_candidates）==========
# 消融实验实测（2026-09-18）：多 Agent 幻觉率 26% vs 单 Agent 4%，
# 且 6 个幻觉全部落在辩论触发的用例上。根因是辩论会用「报修信息 + 驳回理由」
# 重新检索，查询更宽，捞回的资料可能来自其他故障条目；辩论提示词又没要求
# 新证据必须仍属本条故障，于是诊断师把跨段的"轴承损坏"当补充证据写了进去。

_SCOPE_EVIDENCE = """【资料1】
一、离心泵不出水
故障现象：泵启动后压力表无读数，出口无流量。
可能原因：
1. 泵体内未灌满液体，发生气缚。
2. 吸入管路漏气或底阀失效。
3. 电机转向与泵要求方向相反。
4. 吸入高度超过允许吸上真空高度。"""


def test_out_of_scope_candidate_is_dropped():
    """辩论新增、且初检证据里无出处的原因必须被丢弃（这是幻觉的直接来源）。"""
    import agents

    initial = "吸入管路漏气或底阀失效；电机转向与泵要求方向相反"
    # "泵入口过滤器堵塞" 来自液压系统 H-110 条目，不属于离心泵本条
    final = "吸入管路漏气或底阀失效；电机转向与泵要求方向相反；泵入口过滤器堵塞"
    out = agents.drop_out_of_scope_candidates(initial, final, _SCOPE_EVIDENCE)

    assert "泵入口过滤器堵塞" not in out, "越界原因没有被清除"
    assert "吸入管路漏气或底阀失效" in out


def test_in_scope_new_candidate_is_kept():
    """有依据的新增项必须保留——护栏不能把辩论的价值一起砍掉。

    只测"越界被删"会让护栏越改越严、最后恒等于"退回初诊"，
    那样多 Agent 就白做了。这条是对偶约束。
    """
    import agents

    initial = "吸入管路漏气或底阀失效；电机转向与泵要求方向相反"
    final = initial + "；吸入高度超过允许吸上真空高度"
    out = agents.drop_out_of_scope_candidates(initial, final, _SCOPE_EVIDENCE)

    assert "吸入高度超过允许吸上真空高度" in out, "有依据的新增项被误删"


def test_internal_comma_in_initial_candidate_is_not_treated_as_new():
    """初诊自带的项不得因拆分粒度被判成"辩论新增"。

    `_candidate_causes_of` 按全角逗号拆分，"泵体内未灌满液体，发生气缚" 会被
    切成两段。若只靠拆分后的列表比对，初诊自带的条目会被误判成越界而删除
    （实测踩过）。护栏必须额外做规范化子串比对。
    """
    import agents

    initial = "泵体内未灌满液体，发生气缚；吸入管路漏气或底阀失效"
    final = "吸入管路漏气或底阀失效；泵体内未灌满液体；发生气缚"
    out = agents.drop_out_of_scope_candidates(initial, final, _SCOPE_EVIDENCE)

    assert "泵体内未灌满液体" in out
    assert "发生气缚" in out


def test_scope_guard_never_rewrites_degraded_conclusion():
    """降级结论一律不得被护栏改写（沿用全局铁律）。"""
    import agents

    degraded = "知识库无相关依据，无法诊断"
    out = agents.drop_out_of_scope_candidates("轴承损坏", degraded, _SCOPE_EVIDENCE)
    assert out == degraded


def test_scope_guard_returns_initial_when_everything_is_out_of_scope():
    """全部候选都越界时退回初诊，而不是交出一个空结论。"""
    import agents

    initial = "吸入管路漏气或底阀失效"
    final = "完全无关的原因甲；完全无关的原因乙"
    out = agents.drop_out_of_scope_candidates(initial, final, _SCOPE_EVIDENCE)

    assert out == initial, "全越界时应退回初诊，而不是给出无依据的结论"


def test_scope_guard_is_wired_into_agent_rebuttal(monkeypatch):
    """护栏必须真的接在 agent_rebuttal 上——**驱动真实函数**，不做源码字符串检查。

    为什么不用 `inspect.getsource` + 字符串断言：实测过，把接线条件改成
    `if False and ...`（等于彻底断开）后，函数名仍在源码里，字符串检查照样通过。
    那种测试只能证明"代码里出现过这个名字"，不能证明"它被执行"。
    """
    import agents

    # 桩：LLM 返回的辩论结论里含一条越界原因（初检证据里没有出处）
    class _FakeRebuttal:
        def model_dump(self):
            return {
                "行动": "修正",
                "最终根因": "吸入管路漏气或底阀失效；泵入口过滤器堵塞",  # 后者来自别的条目
                "依据": "资料1",
                "置信度": 80,
                "反驳理由": "补充证据",
            }

    monkeypatch.setattr(agents, "invoke_and_validate", lambda *a, **kw: _FakeRebuttal())

    out = agents.agent_rebuttal(
        diagnosis={"根因判断": "吸入管路漏气或底阀失效"},
        review={"理由": "依据不足"},
        evidence=_SCOPE_EVIDENCE,
        fault='{"设备类型": "离心泵", "排除条件": []}',
        initial_evidence=_SCOPE_EVIDENCE,
    )

    root = out.get("最终根因", "")
    assert "泵入口过滤器堵塞" not in root, f"越界护栏没有生效，越界原因仍在：{root}"
    assert "吸入管路漏气或底阀失效" in root, "正常候选被误删"


def test_restore_runs_after_scope_guard(monkeypatch):
    """顺序约束：先清越界，再补丢失。

    反过来的话，"补丢失"会把初诊候选重新拼到结果里，
    而"清越界"已经跑完 —— 顺序错了结果虽然看起来正常，
    但一旦初诊本身含越界项（初诊也可能抄了别的条目），就漏防了。
    这里用"初诊含越界项"的场景把顺序钉死。
    """
    import agents

    class _FakeRebuttal:
        def model_dump(self):
            return {
                "行动": "维持",
                "最终根因": "吸入管路漏气或底阀失效",
                "依据": "资料1", "置信度": 80, "反驳理由": "x",
            }

    monkeypatch.setattr(agents, "invoke_and_validate", lambda *a, **kw: _FakeRebuttal())

    out = agents.agent_rebuttal(
        # 初诊就带了一条越界项（模拟初诊阶段抄了其他条目）
        diagnosis={"根因判断": "吸入管路漏气或底阀失效；泵入口过滤器堵塞"},
        review={"理由": "依据不足"},
        evidence=_SCOPE_EVIDENCE,
        fault='{"设备类型": "离心泵", "排除条件": []}',
        initial_evidence=_SCOPE_EVIDENCE,
    )

    root = out.get("最终根因", "")
    assert "泵入口过滤器堵塞" not in root, "初诊带进来的越界项没有被清除（顺序反了？）"

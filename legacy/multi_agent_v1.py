"""早期原型脚本（历史参考，不再维护）。

正式入口见根目录：orchestrator.py（状态机）/ app.py（前端）/ api.py（接口）。
这些脚本依赖根目录的 .env 与 chroma_db/，请从项目根目录运行，例如：
    python legacy/search_test.py
"""
import os
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_chroma import Chroma

load_dotenv()

# 初始化模型
llm = ChatOpenAI(
    model="Qwen/Qwen2.5-14B-Instruct",
    openai_api_key=os.getenv("SILICONFLOW_API_KEY"),
    openai_api_base=os.getenv("SILICONFLOW_BASE_URL"),
    temperature=0.1
)

# 加载知识库
embeddings = OpenAIEmbeddings(
    model="BAAI/bge-m3",
    openai_api_key=os.getenv("SILICONFLOW_API_KEY"),
    openai_api_base=os.getenv("SILICONFLOW_BASE_URL")
)
db = Chroma(persist_directory="chroma_db", embedding_function=embeddings)

# 用户报修信息
fault_description = """
设备类型：数控机床主轴电机
报警代码：E-203
现象：主轴转速不稳定，异响，温升异常
"""

# 检索资料
retrieved_docs = db.similarity_search(fault_description, k=3)
evidence_text = "\n\n".join([f"【资料{i}】\n{doc.page_content}" for i, doc in enumerate(retrieved_docs, 1)])

# ============ Agent 1: 故障诊断师 ============
def agent_diagnose(evidence, fault):
    prompt = f"""
你是工业设备故障诊断师。请基于以下资料，分析用户报告的故障，找出最可能的根因。

【资料】
{evidence}

【用户报修】
{fault}

严格输出JSON：
{{
    "报警代码": "xxx",
    "根因判断": "xxx",
    "依据": "见资料X",
    "排查建议": ["xxx", "xxx"]
}}
"""
    response = llm.invoke([SystemMessage(content="你是严谨的故障诊断专家。"), HumanMessage(content=prompt)])
    return response.content

# ============ Agent 2: 维修方案审核师 ============
def agent_review(diagnosis_text):
    prompt = f"""
你是维修方案审核师。请审核以下诊断结论是否合理、是否有依据、是否安全。

【诊断师输出】
{diagnosis_text}

严格输出JSON：
{{
    "审核意见": "通过/不通过",
    "理由": "xxx",
    "风险提示": "xxx"
}}
"""
    response = llm.invoke([SystemMessage(content="你是严格的维修安全审核员。"), HumanMessage(content=prompt)])
    return response.content

# ============ Agent 3: 备件成本精算师 ============
def agent_cost(review_text, diagnosis_text):
    prompt = f"""
你是备件成本精算师。基于诊断结论和审核意见，估算维修所需备件和成本。

【诊断结论】
{diagnosis_text}

【审核意见】
{review_text}

严格输出JSON：
{{
    "备件清单": ["xxx"],
    "预计成本": "xxx元",
    "预计工时": "xxx小时"
}}
"""
    response = llm.invoke([SystemMessage(content="你是工业维修成本估算专家。"), HumanMessage(content=prompt)])
    return response.content

# ============ Agent 4: 工单生成师 ============
def agent_workorder(diagnosis_text, review_text, cost_text):
    prompt = f"""
你是维修工单生成师。请把以下信息汇总成标准维修工单。

【诊断结论】
{diagnosis_text}

【审核意见】
{review_text}

【成本估算】
{cost_text}

严格输出JSON：
{{
    "工单编号": "WO-20260830-001",
    "故障现象": "xxx",
    "根因": "xxx",
    "维修方案": "xxx",
    "备件清单": ["xxx"],
    "预计成本": "xxx",
    "安全注意事项": "xxx"
}}
"""
    response = llm.invoke([SystemMessage(content="你是维修工单编制员。"), HumanMessage(content=prompt)])
    return response.content

# ============ 主流程：顺序调用四个Agent ============
print("=" * 60)
print("Agent 1: 故障诊断师工作中...")
print("=" * 60)
diag_result = agent_diagnose(evidence_text, fault_description)
print(diag_result)

print("\n" + "=" * 60)
print("Agent 2: 维修方案审核师工作中...")
print("=" * 60)
review_result = agent_review(diag_result)
print(review_result)

print("\n" + "=" * 60)
print("Agent 3: 备件成本精算师工作中...")
print("=" * 60)
cost_result = agent_cost(review_result, diag_result)
print(cost_result)

print("\n" + "=" * 60)
print("Agent 4: 工单生成师工作中...")
print("=" * 60)
workorder_result = agent_workorder(diag_result, review_result, cost_result)
print(workorder_result)

print("\n" + "=" * 60)
print("多Agent协作流程完成")
print("=" * 60)
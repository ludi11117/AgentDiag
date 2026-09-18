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

# 在线 embedding
embeddings = OpenAIEmbeddings(
    model="BAAI/bge-m3",
    openai_api_key=os.getenv("SILICONFLOW_API_KEY"),
    openai_api_base=os.getenv("SILICONFLOW_BASE_URL")
)

db = Chroma(persist_directory="chroma_db", embedding_function=embeddings)

fault_description = """
设备类型：数控机床主轴电机
报警代码：E-203
现象：主轴转速不稳定，异响，温升异常
"""

retrieved_docs = db.similarity_search(fault_description, k=3)
evidence_text = "\n\n".join([f"【资料{i}】\n{doc.page_content}" for i, doc in enumerate(retrieved_docs, 1)])

llm = ChatOpenAI(
    model="Qwen/Qwen2.5-14B-Instruct",
    openai_api_key=os.getenv("SILICONFLOW_API_KEY"),
    openai_api_base=os.getenv("SILICONFLOW_BASE_URL"),
    temperature=0.1
)

system_prompt = """
你是一名工业设备故障诊断工程师。你必须严格遵守以下规则：

1. 你的诊断结论必须基于【检索资料】中的内容
2. 每个结论后必须标注依据来源，格式为（见资料X）
3. 如果检索资料中没有相关信息，必须回答"依据不足，无法判断"
4. 输出格式必须严格遵循JSON：
{
    "报警代码": "xxx",
    "根因判断": "xxx",
    "依据": "见资料X",
    "排查建议": ["xxx", "xxx"]
}
"""

messages = [
    SystemMessage(content=system_prompt),
    HumanMessage(content=f"【检索资料】\n{evidence_text}\n\n【用户报修】\n{fault_description}")
]

response = llm.invoke(messages)

print("=" * 50)
print("RAG诊断结果：")
print("=" * 50)
print(response.content)
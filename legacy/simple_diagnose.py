"""早期原型脚本（历史参考，不再维护）。

正式入口见根目录：orchestrator.py（状态机）/ app.py（前端）/ api.py（接口）。
这些脚本依赖根目录的 .env 与 chroma_db/，请从项目根目录运行，例如：
    python legacy/search_test.py
"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
# 加载 .env 里的密钥
load_dotenv()

# 初始化大模型
llm = ChatOpenAI(
    model="Qwen/Qwen2.5-7B-Instruct",
    openai_api_key=os.getenv("SILICONFLOW_API_KEY"),
    openai_api_base=os.getenv("SILICONFLOW_BASE_URL"),
    temperature=0.1
)

# 模拟一个工业故障场景
fault_description = """
设备类型：数控机床主轴电机
报警代码：E-203
现象：主轴转速不稳定，异响，温升异常（15分钟内从30°C升至85°C）
"""

# 给模型的角色设定
system_prompt = """
你是一名经验丰富的工业设备故障诊断工程师。
请根据用户提供的设备报警信息，给出可能的故障原因列表（按概率排序），并附上排查建议。
"""

messages = [
    SystemMessage(content=system_prompt),
    HumanMessage(content=fault_description)
]

response = llm.invoke(messages)

print("=" * 50)
print("故障诊断结果：")
print("=" * 50)
print(response.content)
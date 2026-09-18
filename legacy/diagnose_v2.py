"""早期原型脚本（历史参考，不再维护）。

正式入口见根目录：orchestrator.py（状态机）/ app.py（前端）/ api.py（接口）。
这些脚本依赖根目录的 .env 与 chroma_db/，请从项目根目录运行，例如：
    python legacy/search_test.py
"""
import os
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

llm = ChatOpenAI(
   model="Qwen/Qwen2.5-14B-Instruct",
    openai_api_key=os.getenv("SILICONFLOW_API_KEY"),
    openai_api_base=os.getenv("SILICONFLOW_BASE_URL"),
    temperature=0.1
)

fault_description = """
设备类型：数控机床主轴电机
报警代码：E-203
现象：主轴转速不稳定，异响，温升异常（15分钟内从30°C升至85°C）
"""

system_prompt = """
你是一名经验丰富的工业设备故障诊断工程师。
请根据用户提供的设备报警信息进行诊断。

你必须严格按照以下JSON格式输出，不要输出任何其他内容：
{
    "报警代码": "从输入中提取的报警代码",
    "故障现象摘要": "用一句话概括现象",
    "可能原因": [
        {"原因": "第一个可能原因", "概率": "高/中/低", "排查建议": "具体怎么排查"},
        {"原因": "第二个可能原因", "概率": "高/中/低", "排查建议": "具体怎么排查"},
        {"原因": "第三个可能原因", "概率": "高/中/低", "排查建议": "具体怎么排查"}
    ]
}
"""

messages = [
    SystemMessage(content=system_prompt),
    HumanMessage(content=fault_description)
]

response = llm.invoke(messages)

print("=" * 50)
print("模型原始输出：")
print("=" * 50)
print(response.content)
print("\n" + "=" * 50)
print("解析后的数据验证：")
print("=" * 50)

data = json.loads(response.content)

print("报警代码：", data["报警代码"])
print("故障现象摘要：", data["故障现象摘要"])

for i, item in enumerate(data["可能原因"], 1):
    print(f"原因{i}：{item['原因']} | 概率：{item['概率']} | 排查建议：{item['排查建议']}")
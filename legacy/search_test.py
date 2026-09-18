"""早期原型脚本（历史参考，不再维护）。

正式入口见根目录：orchestrator.py（状态机）/ app.py（前端）/ api.py（接口）。
这些脚本依赖根目录的 .env 与 chroma_db/，请从项目根目录运行，例如：
    python legacy/search_test.py
"""
import os
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

load_dotenv()

embeddings = OpenAIEmbeddings(
    model="BAAI/bge-m3",
    openai_api_key=os.getenv("SILICONFLOW_API_KEY"),
    openai_api_base=os.getenv("SILICONFLOW_BASE_URL")
)

db = Chroma(persist_directory="chroma_db", embedding_function=embeddings)

query = "主轴转速不稳定，异响，温升异常，报警代码E-203"
results = db.similarity_search(query, k=3)

print("=" * 50)
print("检索结果：")
print("=" * 50)
for i, doc in enumerate(results, 1):
    print(f"\n【片段{i}】")
    print(doc.page_content)
    print("-" * 40)
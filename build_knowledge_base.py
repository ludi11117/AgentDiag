"""构建 / 重建向量知识库。

用法：
    venv\\Scripts\\python.exe build_knowledge_base.py              # 重建（默认：先清空再写入）
    venv\\Scripts\\python.exe build_knowledge_base.py --dry-run    # 只看切分结果，不写库、不调模型
    venv\\Scripts\\python.exe build_knowledge_base.py --append     # 追加写入，不清空

为什么默认是「清空重建」而不是「追加」：
    ``Chroma.from_texts`` 是**追加**语义——集合已存在时它把新文档 add 进去。
    这个脚本此前就是直接调 from_texts，于是每次重跑，库里的块数都翻一倍：
    改完 data/knowledge_base.txt 再跑一次，检索结果里全是近重复条目，
    既白烧 context，又让 RRF 融合被同源文档刷屏（同一份资料占掉多个名额）。
    重建是幂等的（跑 N 次结果一致），追加不是——所以默认选前者。

路径统一取 settings，不再写死：
    - 之前 persist_directory 硬编码成 "chroma_db"，绕过了 settings.CHROMA_PERSIST_DIR。
      容器里 compose 会把 /app/chroma_db 挂载出来，两边一旦不一致，
      就会写出一个"跑在容器里、宿主机看不到"的库。
    - 知识库原文也改成相对本文件定位，之前用相对 cwd 的路径，
      换个目录执行就 FileNotFoundError。
"""

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agents import knowledge_base_health
from config import settings
from logging_config import configure_logging, get_logger

load_dotenv()
configure_logging()

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent
KB_PATH = BASE_DIR / "data" / "knowledge_base.txt"

CHUNK_SIZE = 200
CHUNK_OVERLAP = 30

# 只保留「【设备名常见故障与排查】」及其之后的内容。
# 文件头是**给人看的元信息**（标题、来源说明、免责声明），不该参与检索：
# 它会被切成 200 字的碎片，而检索名额只有 RETRIEVAL_K=3 个，
# 于是「# FlawScope 知识库 —— 维修经验整理」「---」「> 而这正是本项目…」这类
# 碎片会挤掉真正的故障条目。实测（2026-09-18）三个查询里各有 1–2 个名额被这样浪费。
_SECTION_START = re.compile(r"^【.+常见故障与排查】\s*$", re.MULTILINE)


def strip_preamble(text: str) -> str:
    """剥掉文件头，只留设备章节正文。找不到章节标题时原样返回（不静默丢内容）。"""
    m = _SECTION_START.search(text)
    if not m:
        return text
    return text[m.start():]


def _count(db: Chroma) -> int:
    """当前集合里的块数。取不到就返回 -1，只用于打印，不该让脚本失败。"""
    try:
        return len(db.get()["ids"])
    except Exception:
        return -1


def build(dry_run: bool = False, append: bool = False, force: bool = False) -> int:
    if not KB_PATH.exists():
        print(f"找不到知识库原文：{KB_PATH}")
        return 1

    text = KB_PATH.read_text(encoding="utf-8")
    body = strip_preamble(text)
    if len(body) < len(text):
        print(f"已剥离文件头 {len(text) - len(body)} 字符（说明性内容不参与检索）")

    # ---- 格式守卫：必须在任何破坏性操作之前跑 ----
    # 为什么放在 reset_collection() 之前：本脚本是"先清后写"，格式不合格时若先清，
    # 就会留下一个空库（此坑已踩过一次）。格式不对应当在动库之前就拦下。
    health = knowledge_base_health(body)
    print(f"格式自检：解析出 {health['entries']} 条『可能原因』，覆盖 {health['section_count']} 个章节")
    if not health["ok"] and not force:
        print()
        print("=" * 68)
        print("✗ 知识库格式不合格：未能解析出任何『可能原因』条目。")
        print()
        print("  这不是小事——排除条件映射会**静默失效**：系统照样能诊断，")
        print("  但用户说的『已排除某某』不再被遵守，而且不会有任何报错。")
        print()
        print("  请按 docs/数据接入契约.md 调整格式，常见写法均可：")
        print("    · 章节行：  『一、设备名』  或  『## 设备名』")
        print("    · 原因条目：『1. 原因』『1、原因』『- 原因』『可能原因：原因』")
        print()
        print("  调整后先跑自查： python tools/validate_knowledge_base.py")
        print("  确认要带着不合格格式继续构建：加 --force")
        print("=" * 68)
        return 1

    chunks = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    ).split_text(body)
    print(f"原文 {len(text)} 字符 → 正文 {len(body)} 字符 → 切分为 {len(chunks)} 块")

    if dry_run:
        for i, chunk in enumerate(chunks[:5], start=1):
            print(f"  [{i}] {chunk[:60]!r}")
        if len(chunks) > 5:
            print(f"  ...（其余 {len(chunks) - 5} 块省略）")
        print("--dry-run：未写入向量库，也未调用嵌入模型")
        return 0

    if not settings.SILICONFLOW_API_KEY:
        print("缺少 SILICONFLOW_API_KEY，无法生成嵌入。请在 .env 中配置后重试。")
        return 1

    embeddings = OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        openai_api_key=settings.SILICONFLOW_API_KEY,
        openai_api_base=settings.SILICONFLOW_BASE_URL,
    )

    db = Chroma(
        persist_directory=settings.CHROMA_PERSIST_DIR,
        embedding_function=embeddings,
    )
    before = _count(db)

    if append:
        db.add_texts(chunks)
        action = "追加"
    else:
        # 先删集合并重建空集合，再写入 —— 这样重复执行结果稳定
        db.reset_collection()
        db.add_texts(chunks)
        action = "重建"

    after = _count(db)
    print(f"{action}完成：{before} 块 → {after} 块")
    print(f"已保存到 {Path(settings.CHROMA_PERSIST_DIR).resolve()}")
    print("提示：正在运行的服务进程仍持有旧索引，需重启后端才会加载新的知识库。")
    logger.info("knowledge_base_built", action=action, before=before, after=after, chunks=len(chunks))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 / 重建向量知识库")
    parser.add_argument("--dry-run", action="store_true", help="只做切分与预览，不写库、不调模型")
    parser.add_argument("--append", action="store_true", help="追加写入而不清空（默认清空重建）")
    parser.add_argument("--force", action="store_true",
                        help="格式自检不合格时仍然继续（不推荐：排除映射会静默失效）")
    args = parser.parse_args()
    return build(dry_run=args.dry_run, append=args.append, force=args.force)


if __name__ == "__main__":
    sys.exit(main())

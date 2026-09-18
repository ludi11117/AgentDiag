"""知识库接入自查：把数据填进去之前，先确认系统"读得懂"。

用法：
    venv\\Scripts\\python.exe tools/validate_knowledge_base.py                    # 校验默认知识库
    venv\\Scripts\\python.exe tools/validate_knowledge_base.py path/to/your.txt   # 校验自己的文件
    venv\\Scripts\\python.exe tools/validate_knowledge_base.py --strict           # 有告警也算失败

为什么需要这个脚本：
    本项目是**数据接入容器**——知识库换成谁厂里的资料，系统就该按谁的资料答。
    但"灌进去"和"被读懂"是两件事：`extract_kb_causes()` 要能从这个文本里解析出
    『可能原因』条目，排除条件映射（用户说"已排除某某，别再提"）才有候选可用。
    **解析不出来时系统不会报错**——它照样出诊断，只是悄悄不再遵守用户的排除条件。
    这个静默失效很难被发现，所以接入前必须自查。

退出码：0 = 通过；1 = 不合格（可直接用在 CI 或提交前钩子里）。
"""

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agents import knowledge_base_health  # noqa: E402

DEFAULT_KB = BASE_DIR / "data" / "knowledge_base.txt"


def _print_header(path: Path, text: str) -> None:
    print("=" * 68)
    print(f"知识库自查：{path}")
    print(f"文件大小：{len(text)} 字符")
    print("=" * 68)


def validate(path: Path, strict: bool = False) -> int:
    if not path.exists():
        print(f"✗ 找不到文件：{path}")
        return 1

    text = path.read_text(encoding="utf-8")
    _print_header(path, text)

    health = knowledge_base_health(text)
    entries = health["detail"]

    if not health["ok"]:
        print("✗ 不合格：解析出 0 条『可能原因』条目")
        print()
        print("  这意味着**排除条件映射会静默失效**：系统照样能诊断，")
        print("  但你/用户说的『已排除某某』不再被遵守，而且不会有任何报错。")
        print()
        print("  请按 docs/数据接入契约.md 调整格式。常见写法都能识别：")
        print()
        print("    【设备章节名】            或   ## 设备章节名")
        print("    可能原因：                      1. 原因一")
        print("    1. 原因一                       2、原因二")
        print("    2. 原因二                       - 原因三")
        print()
        print("  最容易踩的坑：在『可能原因』下写了内容，却用纯文本/表格/")
        print("  没有列表符号的段落——系统需要一个可识别的条目边界。")
        print("=" * 68)
        return 1

    print(f"✓ 解析出 {health['entries']} 条『可能原因』，覆盖 {health['section_count']} 个章节")
    print()

    # 明细：按章节归组
    by_section: dict = {}
    for sec, cause in entries:
        by_section.setdefault(sec or "（未标注章节）", []).append(cause)
    for sec, causes in by_section.items():
        print(f"  【{sec}】{len(causes)} 条")
        for c in causes[:3]:
            print(f"      · {c[:56]}")
        if len(causes) > 3:
            print(f"      …… 其余 {len(causes) - 3} 条")
    print()

    # 告警（不致命，但值得看一眼）
    warnings = []
    unnamed = sum(1 for sec, _ in entries if not sec)
    if unnamed:
        warnings.append(
            f"{unnamed} 条原因没有归属章节（缺『一、设备名』或『## 设备名』标题行）。"
            "这些条目无法按设备收窄，可能造成跨设备误排除。"
        )
    if health["section_count"] < 2 and health["entries"] > 5:
        warnings.append(
            f"只有 {health['section_count']} 个章节但解析出 {health['entries']} 条原因，"
            "检查是否漏写了设备章节标题。"
        )
    long_entries = [c for _, c in entries if len(c) > 60]
    if long_entries:
        warnings.append(
            f"{len(long_entries)} 条原因超过 60 字，可能是把整段话当成了一条。"
            "建议每条原因写成一句可独立读懂的话。"
        )

    if warnings:
        print("⚠ 提醒（不致命）：")
        for w in warnings:
            print(f"    · {w}")
        print()
        print("=" * 68)
        print("✓ 通过（有提醒）" if not strict else "✗ --strict：存在提醒，判为失败")
        print("=" * 68)
        return 1 if strict else 0

    print("=" * 68)
    print("✓ 全部通过。可以执行：python build_knowledge_base.py")
    print("=" * 68)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库接入自查")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_KB),
                        help="知识库文本路径（默认 data/knowledge_base.txt）")
    parser.add_argument("--strict", action="store_true", help="有提醒也算失败")
    args = parser.parse_args()
    return validate(Path(args.path), strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())

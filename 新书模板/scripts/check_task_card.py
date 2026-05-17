#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re


HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
BANNED_WORDS = ["因为", "所以", "意味着", "体现", "铺垫"]
REQUIRED_HEADINGS = ["本章只办成", "必须承接", "本章禁写", "章尾结果"]


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    return path.read_text(encoding="utf-8")


def collect_heading_bullets(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current = "(root)"
    result[current] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = HEADING_RE.match(line)
        if match:
            current = match.group(1).strip()
            result.setdefault(current, [])
            continue
        if line.startswith("- "):
            result.setdefault(current, []).append(line[2:].strip())
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查当前章任务卡是否命令式、短条化")
    parser.add_argument("task_card", help="当前章任务卡路径")
    parser.add_argument("--max-items", type=int, default=4)
    parser.add_argument("--max-item-chars", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.task_card)
    text = read_text(path)
    sections = collect_heading_bullets(text)

    errors: list[str] = []
    for heading in REQUIRED_HEADINGS:
        if heading not in sections:
            errors.append(f"[缺失] 必须包含栏目：{heading}")
        elif not sections[heading]:
            errors.append(f"[空栏] 栏目没有任务条目：{heading}")

    for heading, items in sections.items():
        if heading == "使用上限":
            continue
        if heading == "(root)":
            continue
        if len(items) > args.max_items:
            errors.append(f"[超条数] {heading} 有 {len(items)} 条，超过 {args.max_items} 条")
        for item in items:
            if len(item) > args.max_item_chars:
                errors.append(f"[过长] {heading} 条目超过 {args.max_item_chars} 字：{item[:42]}...")
            hits = [word for word in BANNED_WORDS if word in item]
            if hits:
                errors.append(f"[解释腔] {heading} 条目含 {','.join(hits)}：{item[:42]}...")

    if errors:
        print("\n".join(errors))
        return 1
    print(f"任务卡通过：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

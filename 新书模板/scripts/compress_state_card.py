#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re


HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
SOURCE_RE = re.compile(r"\[源：第(.+?)章\]")
META_HEADINGS = {
    "使用上限",
    "模板",
    "维护原则",
    "使用说明",
    "元信息",
}


def is_placeholder_item(item: str) -> bool:
    return "第N章" in item or "第X章" in item or "……" in item


def iter_effective_lines(text: str) -> list[str]:
    lines: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        if raw_line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        lines.append(raw_line)
    return lines


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    return path.read_text(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读输出状态卡压缩建议，不自动改文件")
    parser.add_argument("state_card", help="当前卷状态卡路径")
    parser.add_argument("--max-items", type=int, default=4)
    parser.add_argument("--max-item-chars", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.state_card)
    text = read_text(path)
    current = "(root)"
    sections: dict[str, list[str]] = {current: []}

    for raw_line in iter_effective_lines(text):
        line = raw_line.strip()
        match = HEADING_RE.match(line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current in META_HEADINGS:
            continue
        if line.startswith("- "):
            item = line[2:].strip()
            if not is_placeholder_item(item):
                sections.setdefault(current, []).append(item)

    suggestions: list[str] = []
    for heading, items in sections.items():
        if heading == "(root)" or not items:
            continue
        if len(items) > args.max_items:
            suggestions.append(f"[超条数] {heading} 有 {len(items)} 条，建议合并到 {args.max_items} 条以内")
        for item in items:
            if len(item) > args.max_item_chars:
                suggestions.append(f"[过长] {heading} 条目超过 {args.max_item_chars} 字，建议压缩：{item[:50]}...")

        by_source: dict[str, list[str]] = {}
        for item in items:
            match = SOURCE_RE.search(item)
            if not match:
                continue
            by_source.setdefault(match.group(1), []).append(item)
        for source, grouped in by_source.items():
            if len(grouped) > 1:
                suggestions.append(f"[可合并] {heading} 中第{source}章来源有 {len(grouped)} 条，可合并为一条当前有效结果")

    if suggestions:
        print("\n".join(suggestions))
        return 1
    print(f"暂无压缩建议：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

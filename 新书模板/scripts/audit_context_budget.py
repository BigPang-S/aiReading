#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re


HEADING_RE = re.compile(r"^(#+)\s+(.*)$")
META_HEADINGS = {
    "使用上限",
    "模板",
    "维护原则",
    "使用说明",
    "元信息",
}


def is_meta_heading(heading: str) -> bool:
    return heading.strip() in META_HEADINGS


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
        return ""
    return path.read_text(encoding="utf-8")


def count_bullets_by_heading(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    current = "(root)"
    counts[current] = 0
    for raw_line in iter_effective_lines(text):
        line = raw_line.strip()
        match = HEADING_RE.match(line)
        if match:
            current = match.group(2).strip()
            counts.setdefault(current, 0)
            continue
        if line.startswith("- ") and not is_meta_heading(current):
            counts[current] = counts.get(current, 0) + 1
    return counts


def overlong_bullets(text: str, limit: int) -> list[str]:
    results: list[str] = []
    current = "(root)"
    for raw_line in iter_effective_lines(text):
        line = raw_line.strip()
        match = HEADING_RE.match(line)
        if match:
            current = match.group(2).strip()
            continue
        if is_meta_heading(current):
            continue
        if line.startswith("- ") and len(line[2:].strip()) > limit:
            results.append(line[2:].strip())
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计当前章活跃上下文预算")
    parser.add_argument("--rules", default="当前有效规则卡.md", help="规则卡路径")
    parser.add_argument("--volume-card", required=True, help="当前卷状态卡路径")
    parser.add_argument("--task-card", required=True, help="当前章任务卡路径")
    parser.add_argument("--context-pack", default="小说框架/当前章上下文包.md", help="上下文包路径")
    parser.add_argument("--max-rules", type=int, default=1600)
    parser.add_argument("--max-volume", type=int, default=1800)
    parser.add_argument("--max-task", type=int, default=1200)
    parser.add_argument("--max-pack", type=int, default=4000)
    parser.add_argument("--max-item", type=int, default=120)
    return parser.parse_args()


def report_length(label: str, path: Path, text: str, limit: int) -> list[str]:
    status = "OK" if len(text) <= limit else "WARN"
    return [f"[{status}] {label}：{len(text)} 字 / {limit} - {path}"]


def main() -> int:
    args = parse_args()
    files = {
        "当前有效规则卡": (Path(args.rules), args.max_rules),
        "当前卷状态卡": (Path(args.volume_card), args.max_volume),
        "当前章任务卡": (Path(args.task_card), args.max_task),
        "当前章上下文包": (Path(args.context_pack), args.max_pack),
    }

    lines: list[str] = []
    warnings: list[str] = []
    for label, (path, limit) in files.items():
        text = read_text(path)
        if not text:
            warnings.append(f"[WARN] {label} 不存在或为空：{path}")
            continue
        lines.extend(report_length(label, path, text, limit))
        if label in {"当前卷状态卡", "当前章任务卡"}:
            long_items = overlong_bullets(text, args.max_item)
            for item in long_items[:5]:
                warnings.append(f"[WARN] {label} 存在超过 {args.max_item} 字条目：{item[:42]}...")
            for heading, count in count_bullets_by_heading(text).items():
                if heading != "(root)" and count > 4:
                    warnings.append(f"[WARN] {label} 的“{heading}”有 {count} 条，超过 4 条")

    pack_text = read_text(Path(args.context_pack))
    if "当前有效规则卡" in pack_text and "当前卷执行状态卡" in pack_text:
        warnings.append("[INFO] 上下文包已包含三卡，投喂模型时不要重复附送源卡")

    print("\n".join(lines))
    if warnings:
        print("\n".join(warnings))
    return 1 if any(item.startswith("[WARN]") for item in warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

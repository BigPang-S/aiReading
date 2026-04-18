#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
import sys


HEADING_RE = re.compile(r"^(#+)\s+(.*)$")


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    return path.read_text(encoding="utf-8")


def count_bullets_by_heading(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    current = "(root)"
    counts[current] = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = HEADING_RE.match(line)
        if match:
            current = match.group(2).strip()
            counts.setdefault(current, 0)
            continue
        if line.startswith("- "):
            counts[current] = counts.get(current, 0) + 1
    return counts


def find_heading_count(counts: dict[str, int], keyword: str) -> int:
    for heading, count in counts.items():
        if keyword in heading:
            return count
    return 0


def validate_budget(name: str, text: str, limits: dict[str, int]) -> list[str]:
    counts = count_bullets_by_heading(text)
    errors: list[str] = []
    for heading, limit in limits.items():
        count = find_heading_count(counts, heading)
        if count > limit:
            errors.append(f"{name} 的“{heading}”有 {count} 条，超过上限 {limit} 条")
    return errors


def extract_default_rereads(text: str) -> list[str]:
    results: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("- 默认回读："):
            value = line.removeprefix("- 默认回读：").strip().rstrip("。")
            value = re.sub(r"^只回读", "", value).strip()
            value = re.sub(r"[，,].*$", "", value).strip()
            results.append(value)
    return results


def build_context_pack(rule_text: str, volume_text: str, task_text: str, volume_path: Path, task_path: Path) -> str:
    rereads = extract_default_rereads(volume_text) + extract_default_rereads(task_text)
    unique_rereads: list[str] = []
    for item in rereads:
        if item and item not in unique_rereads:
            unique_rereads.append(item)

    lines = [
        "# 当前章最小上下文包",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 使用规则：默认只把这份文件和当前待写正文交给模型；不要补读进度记录、验收记录、归档和全量总目录。",
        f"- 当前卷状态卡：{volume_path}",
        f"- 当前章任务卡：{task_path}",
    ]
    if unique_rereads:
        lines.append(f"- 默认回读：{'；'.join(unique_rereads)}")
    lines.extend(
        [
            "",
            "## 1. 当前有效规则卡",
            "",
            rule_text.strip(),
            "",
            "## 2. 当前卷执行状态卡",
            "",
            volume_text.strip(),
            "",
            "## 3. 当前章任务卡",
            "",
            task_text.strip(),
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成本章最小上下文包，并检查状态卡/任务卡预算")
    parser.add_argument("--rules", default="当前有效规则卡.md", help="规则卡文件，默认 当前有效规则卡.md")
    parser.add_argument("--volume-card", required=True, help="当前卷执行状态卡路径")
    parser.add_argument("--task-card", required=True, help="当前章任务卡路径")
    parser.add_argument("--output", required=True, help="输出的上下文包路径")
    parser.add_argument("--max-chars", type=int, default=4000, help="上下文包默认最大字符数，默认 4000")
    parser.add_argument("--force", action="store_true", help="超预算时仍然输出文件")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rule_path = Path(args.rules)
    volume_path = Path(args.volume_card)
    task_path = Path(args.task_card)
    output_path = Path(args.output)

    rule_text = read_text(rule_path)
    volume_text = read_text(volume_path)
    task_text = read_text(task_path)

    state_limits = {
        "主线进度": 4,
        "资源 / 经营": 4,
        "人物位置": 4,
        "关系 / 外部压力": 4,
        "待确认事项": 3,
        "禁越界": 3,
        "下一章执行口": 3,
    }
    task_limits = {
        "本章只办成这 3 件事": 3,
        "本章必须承接": 4,
        "本章不能写": 4,
        "建议调用": 3,
        "本章完成判定": 4,
        "写完后回填": 4,
    }

    errors = []
    errors.extend(validate_budget("当前卷执行状态卡", volume_text, state_limits))
    errors.extend(validate_budget("当前章任务卡", task_text, task_limits))

    content = build_context_pack(rule_text, volume_text, task_text, volume_path, task_path)
    char_count = len(content)
    if char_count > args.max_chars:
        errors.append(f"当前章最小上下文包长度为 {char_count} 字，超过预算 {args.max_chars} 字")

    if errors and not args.force:
        for item in errors:
            print(f"[超预算] {item}", file=sys.stderr)
        print("请先压缩状态卡或任务卡，再重新生成上下文包。", file=sys.stderr)
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"已生成：{output_path}")
    print(f"长度：{char_count} 字")
    if errors:
        for item in errors:
            print(f"[警告] {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
import sys


HEADING_RE = re.compile(r"^(#+)\s+(.*)$")
SKILL_ALIASES = {
    "总控": "小说写作总控skill",
    "小说写作总控": "小说写作总控skill",
    "章节验收": "章节验收与连续性校验",
}


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


def validate_bullet_lengths(name: str, text: str, max_chars: int) -> list[str]:
    errors: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        body = line[2:].strip()
        if len(body) > max_chars:
            errors.append(f"{name} 存在超过 {max_chars} 字的条目：{body[:36]}...")
    return errors[:6]


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


def normalize_skill_name(raw: str) -> str:
    value = raw.strip().strip("`：:，,。；; ")
    value = re.sub(r"^(主|辅|主调用|次调用)\s*[：:]\s*", "", value)
    value = value.strip("`：:，,。；; ")
    return SKILL_ALIASES.get(value, value)


def extract_recommended_skills(task_text: str) -> list[str]:
    skills: list[str] = []
    in_section = False
    for raw_line in task_text.splitlines():
        line = raw_line.strip()
        heading = HEADING_RE.match(line)
        if heading:
            in_section = any(keyword in heading.group(2) for keyword in ["建议调用", "建议技能"])
            continue
        if not in_section or not line.startswith("- "):
            continue
        item = normalize_skill_name(line[2:])
        if item and item not in skills:
            skills.append(item)
    return skills[:3]


def extract_skill_sections(skill_card_text: str, skill_names: list[str]) -> str:
    if not skill_names:
        return ""

    sections: dict[str, list[str]] = {}
    current: str | None = None
    bucket: list[str] = []
    for raw_line in skill_card_text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", raw_line)
        if match:
            if current and bucket:
                sections[current] = bucket
            current = match.group(1).strip()
            bucket = [raw_line]
            continue
        if current:
            bucket.append(raw_line)
    if current and bucket:
        sections[current] = bucket

    selected: list[str] = []
    for name in skill_names:
        section = sections.get(name)
        if section:
            selected.append("\n".join(section).strip())
    return "\n\n".join(selected)


def build_context_pack(
    rule_text: str,
    volume_text: str,
    task_text: str,
    volume_path: Path,
    task_path: Path,
    skill_capsule: str,
) -> str:
    rereads = extract_default_rereads(volume_text) + extract_default_rereads(task_text)
    unique_rereads: list[str] = []
    for item in rereads:
        if item and item not in unique_rereads:
            unique_rereads.append(item)

    lines = [
        "# 当前章最小上下文包",
        "",
        "```yaml",
        "chapter_context:",
        f"  generated_at: \"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\"",
        "  feed_rule: \"只把本上下文包、当前待写/待修正文和必要前章交给模型\"",
        "  dedupe_rule: \"本包已包含规则卡、状态卡、任务卡；不要重复附送源卡\"",
        f"  volume_card: \"{volume_path}\"",
        f"  task_card: \"{task_path}\"",
        "  default_do_not_read:",
        "    - 进度记录.md",
        "    - 章节验收记录.md",
        "    - 归档/",
        "    - 小说框架/03_总目录.md",
        "    - 完整 skill",
        "    - 完整 workflow",
    ]
    if unique_rereads:
        lines.append("  reread:")
        for item in unique_rereads:
            lines.append(f"    - \"{item}\"")
    lines.append("```")
    lines.extend(
        [
            "",
            "## project_rules",
            "",
            rule_text.strip(),
            "",
            "## current_volume",
            "",
            volume_text.strip(),
            "",
            "## current_chapter",
            "",
            task_text.strip(),
            "",
        ]
    )
    if skill_capsule:
        lines.extend(["## skill_capsule", "", skill_capsule.strip(), ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成本章最小上下文包，并检查状态卡/任务卡预算")
    parser.add_argument("--rules", default="当前有效规则卡.md", help="规则卡文件，默认 当前有效规则卡.md")
    parser.add_argument("--volume-card", required=True, help="当前卷执行状态卡路径")
    parser.add_argument("--task-card", required=True, help="当前章任务卡路径")
    parser.add_argument("--output", required=True, help="输出的上下文包路径")
    parser.add_argument("--skill-card", default="SOP资料/skills/技能短卡.md", help="技能短卡路径，默认 SOP资料/skills/技能短卡.md")
    parser.add_argument("--max-chars", type=int, default=4000, help="上下文包默认最大字符数，默认 4000")
    parser.add_argument("--max-rules-chars", type=int, default=1600, help="规则卡默认最大字符数，默认 1600")
    parser.add_argument("--max-volume-chars", type=int, default=1800, help="状态卡默认最大字符数，默认 1800")
    parser.add_argument("--max-task-chars", type=int, default=1200, help="任务卡默认最大字符数，默认 1200")
    parser.add_argument("--force", action="store_true", help="超预算时仍然输出文件")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rule_path = Path(args.rules)
    volume_path = Path(args.volume_card)
    task_path = Path(args.task_card)
    output_path = Path(args.output)
    skill_card_path = Path(args.skill_card)

    rule_text = read_text(rule_path)
    volume_text = read_text(volume_path)
    task_text = read_text(task_path)
    skill_card_text = read_text(skill_card_path) if skill_card_path.exists() else ""
    recommended_skills = extract_recommended_skills(task_text)
    skill_capsule = extract_skill_sections(skill_card_text, recommended_skills)

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
        "本章只办成": 3,
        "必须承接": 4,
        "本章禁写": 4,
        "章尾结果": 4,
        "建议技能": 3,
        "写完后回填": 4,
    }

    errors = []
    errors.extend(validate_budget("当前卷执行状态卡", volume_text, state_limits))
    errors.extend(validate_budget("当前章任务卡", task_text, task_limits))
    errors.extend(validate_bullet_lengths("当前卷执行状态卡", volume_text, 120))
    errors.extend(validate_bullet_lengths("当前章任务卡", task_text, 120))
    section_lengths = {
        "规则卡": len(rule_text.strip()),
        "状态卡": len(volume_text.strip()),
        "任务卡": len(task_text.strip()),
        "技能短卡": len(skill_capsule.strip()),
    }
    if section_lengths["规则卡"] > args.max_rules_chars:
        errors.append(
            f"规则卡长度为 {section_lengths['规则卡']} 字，超过上限 {args.max_rules_chars} 字"
        )
    if section_lengths["状态卡"] > args.max_volume_chars:
        errors.append(
            f"当前卷执行状态卡长度为 {section_lengths['状态卡']} 字，超过上限 {args.max_volume_chars} 字"
        )
    if section_lengths["任务卡"] > args.max_task_chars:
        errors.append(
            f"当前章任务卡长度为 {section_lengths['任务卡']} 字，超过上限 {args.max_task_chars} 字"
        )

    content = build_context_pack(rule_text, volume_text, task_text, volume_path, task_path, skill_capsule)
    char_count = len(content)
    section_lengths["包头"] = char_count - sum(section_lengths.values())
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
    print(
        "分段："
        f"规则卡 {section_lengths['规则卡']} / "
        f"状态卡 {section_lengths['状态卡']} / "
        f"任务卡 {section_lengths['任务卡']} / "
        f"技能短卡 {section_lengths['技能短卡']} / "
        f"包头 {section_lengths['包头']}"
    )
    if errors:
        for item in errors:
            print(f"[警告] {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

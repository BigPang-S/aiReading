#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行章节验收并自动写入章节验收记录")
    parser.add_argument("--chapter", required=True, help="当前章节文件，相对项目根目录或绝对路径")
    parser.add_argument("--project-root", help="项目根目录，默认取脚本所在目录的上一层")
    parser.add_argument("--rules", help="规则文件，默认 项目规则.md")
    parser.add_argument("--outline", help="总目录文件，默认 小说框架/03_总目录.md")
    parser.add_argument("--previous-dir", help="正文目录，默认 小说正文")
    parser.add_argument("--record", help="验收记录文件，默认 章节验收记录.md")
    parser.add_argument("--skip-log", action="store_true", help="只运行验收，不写入记录")
    return parser.parse_args()


def resolve_project_root(args: argparse.Namespace) -> Path:
    if args.project_root:
        return Path(args.project_root).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def resolve_under(root: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (root / path).resolve()


def find_guard_script(project_root: Path) -> tuple[Path, Path]:
    for base in [project_root, *project_root.parents]:
        candidate = base / "skills" / "novel-chapter-acceptance" / "scripts" / "chapter_guard.py"
        if candidate.exists():
            return candidate, base

    local_candidate = project_root / "SOP资料" / "skills" / "novel-chapter-acceptance" / "scripts" / "chapter_guard.py"
    if local_candidate.exists():
        return local_candidate, project_root

    raise FileNotFoundError(
        "未找到 skills/novel-chapter-acceptance/scripts/chapter_guard.py，也未找到模板内置 SOP资料/skills/novel-chapter-acceptance/scripts/chapter_guard.py"
    )


def pick_first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def pick_outline(project_root: Path) -> Path | None:
    direct = pick_first_existing(
        [
            project_root / "小说框架" / "03_总目录.md",
            project_root / "小说框架" / "03_总目录.docx",
            project_root / "小说框架" / "03_总目录.txt",
        ]
    )
    if direct:
        return direct
    frame_dir = project_root / "小说框架"
    if not frame_dir.exists():
        return None
    candidates = sorted(
        [
            path
            for path in frame_dir.iterdir()
            if path.is_file() and path.name.startswith("03_") and "总目录" in path.name
        ]
    )
    for path in candidates:
        if path.suffix.lower() in {".md", ".docx", ".txt"}:
            return path
    return None


def build_guard_command(
    guard_script: Path,
    chapter: Path,
    rules: Path | None,
    outline: Path | None,
    previous_dir: Path | None,
) -> list[str]:
    command = [
        "python3",
        str(guard_script),
        "--chapter",
        str(chapter),
        "--format",
        "json",
    ]
    if rules:
        command.extend(["--rules", str(rules)])
    if outline:
        command.extend(["--outline", str(outline)])
    if previous_dir and previous_dir.exists():
        command.extend(["--previous-dir", str(previous_dir)])
    return command


def run_guard(command: list[str], cwd: Path) -> tuple[int, dict]:
    completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
    if completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr)
    if not completed.stdout.strip():
        raise RuntimeError("章节验收脚本没有输出结果")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"章节验收脚本输出不是有效 JSON: {exc}") from exc
    return completed.returncode, report


def to_project_relative(path: str | Path, project_root: Path) -> str:
    target = Path(path)
    try:
        return str(target.resolve().relative_to(project_root))
    except Exception:
        return str(target)


def append_record(record_path: Path, project_root: Path, report: dict, command: list[str]) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    outline_entries = report.get("outline_entries") or []
    failures = report.get("failures") or []
    warnings = report.get("warnings") or []
    passes = report.get("passes") or []
    file_label = to_project_relative(report["file"], project_root)
    rules = report.get("rules", {})

    lines = []
    lines.append("")
    lines.append(f"## {timestamp} {report.get('title', '未识别标题')}")
    lines.append(f"- 文件：{file_label}")
    lines.append(f"- 验收结论：{report.get('overall', '未知')}")
    lines.append(f"- 正文字数：{report.get('body_chars', '未知')}")
    lines.append(
        f"- 验收规则：目标 {rules.get('target_min', '?')}-{rules.get('target_max', '?')}，最低 {rules.get('absolute_min', '?')}"
    )
    lines.append(f"- 执行命令：`{' '.join(command)}`")
    if outline_entries:
        lines.append(f"- 大纲匹配：{outline_entries[0]}")
    else:
        lines.append("- 大纲匹配：未定位到条目，需人工确认")

    if failures:
        lines.append("- 阻塞问题：")
        for item in failures:
            lines.append(f"  - {item}")
    else:
        lines.append("- 阻塞问题：无")

    if warnings:
        lines.append("- 风险警告：")
        for item in warnings:
            lines.append(f"  - {item}")
    else:
        lines.append("- 风险警告：无")

    if passes:
        lines.append("- 通过项摘要：")
        for item in passes[:6]:
            lines.append(f"  - {item}")
    else:
        lines.append("- 通过项摘要：无")

    next_action = {
        "通过": "可进入下一章，人工补一句“这章推进了什么”后继续。",
        "警告": "可继续，但先人工确认风险点是否会影响后续大纲推进。",
        "不通过": "先修阻塞问题，再重新运行一次验收。",
    }.get(report.get("overall"), "请人工复核。")
    lines.append(f"- 下一步建议：{next_action}")

    if not record_path.exists():
        record_path.write_text("# 章节验收记录\n", encoding="utf-8")
    with record_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
        fh.write("\n")


def main() -> int:
    args = parse_args()
    project_root = resolve_project_root(args)
    guard_script, guard_cwd = find_guard_script(project_root)

    chapter = resolve_under(project_root, args.chapter)
    if chapter is None or not chapter.exists():
        print(f"找不到章节文件：{args.chapter}", file=sys.stderr)
        return 1

    rules = resolve_under(project_root, args.rules) if args.rules else pick_first_existing([project_root / "项目规则.md"])
    outline = (
        resolve_under(project_root, args.outline)
        if args.outline
        else pick_outline(project_root)
    )
    previous_dir = resolve_under(project_root, args.previous_dir) if args.previous_dir else project_root / "小说正文"
    record = resolve_under(project_root, args.record) if args.record else project_root / "章节验收记录.md"

    command = build_guard_command(guard_script, chapter, rules, outline, previous_dir)
    exit_code, report = run_guard(command, guard_cwd)

    summary = [
        "章节自动验收完成",
        f"结论：{report.get('overall')}",
        f"文件：{to_project_relative(report.get('file', ''), project_root)}",
        f"标题：{report.get('title')}",
        f"正文字数：{report.get('body_chars')}",
    ]
    if report.get("failures"):
        summary.append("阻塞问题：")
        for item in report["failures"]:
            summary.append(f"- {item}")
    if report.get("warnings"):
        summary.append("风险警告：")
        for item in report["warnings"]:
            summary.append(f"- {item}")
    print("\n".join(summary))

    if not args.skip_log and record is not None:
        append_record(record, project_root, report, command)
        print(f"已写入验收记录：{to_project_relative(record, project_root)}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

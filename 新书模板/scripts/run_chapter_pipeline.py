#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from render_chapter_docx import build_docx, count_body_chars, load_text_chapter
from run_chapter_acceptance import (
    AUTO_ARCHIVE_DIRNAME,
    append_record,
    append_archive_blocks,
    build_guard_command,
    enrich_style_warnings,
    find_guard_script,
    pick_first_existing,
    pick_outline,
    resolve_under,
    run_guard,
    to_project_relative,
)


PROGRESS_RECORD_START_RE = re.compile(r"^- 记录时间：.*$", re.M)
PROGRESS_FILE_RE = re.compile(r"^- 文件：\s*(.+?)\s*$", re.M)
PROGRESS_AUTO_ARCHIVE_NAME = "进度记录_自动归档.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键执行 txt 渲染、章节验收和短记录追加")
    parser.add_argument("--input", required=True, help="输入 txt 文件")
    parser.add_argument("--output", help="输出 docx 文件；默认自动推导")
    parser.add_argument("--project-root", help="项目根目录，默认取脚本所在目录的上一层")
    parser.add_argument("--rules", help="规则文件，默认 当前有效规则卡.md")
    parser.add_argument("--outline", help="总目录文件；默认不读取，任务卡缺失或推进错位时再显式传入")
    parser.add_argument("--previous-dir", help="正文目录；默认不读取，连续性无法判断时再显式传入")
    parser.add_argument("--record", help="验收记录文件，默认 章节验收记录.md")
    parser.add_argument(
        "--log-mode",
        choices=["concise", "full"],
        default="concise",
        help="写入验收记录时使用短记录或完整记录，默认 concise",
    )
    parser.add_argument(
        "--progress-record",
        help="进度记录文件，默认 进度记录.md",
    )
    parser.add_argument("--skip-acceptance-log", action="store_true", help="只跑验收，不写入章节验收记录")
    parser.add_argument("--skip-progress-log", action="store_true", help="不写入进度记录短条")
    return parser.parse_args()


def resolve_project_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def infer_output_path(input_path: Path, project_root: Path) -> Path:
    source_dir = project_root / "小说正文" / "源稿"
    try:
        relative = input_path.relative_to(source_dir)
    except ValueError:
        return input_path.with_suffix(".docx")
    return (project_root / "小说正文" / relative).with_suffix(".docx")


def ensure_progress_heading(progress_record: Path) -> None:
    if not progress_record.exists():
        progress_record.write_text("# 进度记录\n\n## 自动流水线记录\n", encoding="utf-8")
        return

    content = progress_record.read_text(encoding="utf-8")
    if "## 自动流水线记录" not in content:
        with progress_record.open("a", encoding="utf-8") as fh:
            if not content.endswith("\n"):
                fh.write("\n")
            fh.write("\n## 自动流水线记录\n")


def split_progress_log(content: str) -> tuple[str, list[str]]:
    heading_match = re.search(r"^## 自动流水线记录\s*$", content, re.M)
    if not heading_match:
        return content.rstrip() + "\n\n## 自动流水线记录\n", []

    line_end = content.find("\n", heading_match.start())
    if line_end == -1:
        prefix = content.rstrip() + "\n"
        body = ""
    else:
        prefix = content[: line_end + 1]
        body = content[line_end + 1 :]

    matches = list(PROGRESS_RECORD_START_RE.finditer(body))
    if not matches:
        return prefix, []

    blocks: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        blocks.append(body[match.start() : end])
    return prefix, blocks


def extract_progress_file_label(block: str) -> str | None:
    match = PROGRESS_FILE_RE.search(block)
    if not match:
        return None
    return match.group(1).strip()


def append_progress_record(
    progress_record: Path,
    project_root: Path,
    input_path: Path,
    output_path: Path,
    source_chars: int,
    report: dict,
) -> None:
    ensure_progress_heading(progress_record)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    input_label = to_project_relative(input_path, project_root)
    output_label = to_project_relative(output_path, project_root)
    file_label = f"`{input_label}` -> `{output_label}`"
    overall = report.get("overall", "未知")
    status = {
        "通过": "已完成（验收通过）",
        "警告": "已完成（验收警告）",
        "不通过": "待修订（验收不通过）",
    }.get(overall, "请人工复核")

    lines = [
        f"- 记录时间：{timestamp}",
        f"- 文件：`{input_label}` -> `{output_label}`",
        f"- 修改内容摘要：源稿渲染 docx，并自动验收为{overall}。",
        f"- 改前字数：源稿正文 {source_chars}",
        f"- 改后字数：docx 正文 {report.get('body_chars', '未知')}",
        f"- 当前状态：{status}",
    ]
    entry = "\n".join(lines).rstrip() + "\n"

    content = progress_record.read_text(encoding="utf-8")
    prefix, blocks = split_progress_log(content)
    displaced = [block for block in blocks if extract_progress_file_label(block) == file_label]
    kept = [block for block in blocks if extract_progress_file_label(block) != file_label]

    append_archive_blocks(
        project_root / AUTO_ARCHIVE_DIRNAME / PROGRESS_AUTO_ARCHIVE_NAME,
        "进度记录自动归档",
        displaced,
    )

    parts: list[str] = [prefix.rstrip()]
    parts.extend(block.strip() for block in kept if block.strip())
    parts.append(entry.strip())
    progress_record.write_text("\n\n".join(parts) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    project_root = resolve_project_root(args.project_root)

    input_path = resolve_under(project_root, args.input)
    if input_path is None or not input_path.exists():
        print(f"找不到源稿文件：{args.input}", file=sys.stderr)
        return 1
    if input_path.suffix.lower() != ".txt":
        print(f"源稿文件必须是 .txt：{input_path}", file=sys.stderr)
        return 1

    output_path = resolve_under(project_root, args.output) if args.output else infer_output_path(input_path, project_root)
    if output_path is None:
        print("无法推导输出路径", file=sys.stderr)
        return 1

    title, paragraphs = load_text_chapter(input_path)
    source_chars = count_body_chars(paragraphs)
    build_docx(title, paragraphs, output_path)

    guard_script = find_guard_script(project_root)
    rules = (
        resolve_under(project_root, args.rules)
        if args.rules
        else pick_first_existing([project_root / "当前有效规则卡.md"])
    )
    outline = resolve_under(project_root, args.outline) if args.outline else None
    previous_dir = resolve_under(project_root, args.previous_dir) if args.previous_dir else None
    acceptance_record = resolve_under(project_root, args.record) if args.record else project_root / "章节验收记录.md"
    progress_record = (
        resolve_under(project_root, args.progress_record)
        if args.progress_record
        else project_root / "进度记录.md"
    )

    command = build_guard_command(guard_script, output_path, rules, outline, previous_dir)
    exit_code, report = run_guard(command, project_root)
    enrich_style_warnings(report, output_path)

    if not args.skip_acceptance_log and acceptance_record is not None:
        append_record(acceptance_record, project_root, report, command, args.log_mode)

    if not args.skip_progress_log and progress_record is not None:
        append_progress_record(progress_record, project_root, input_path, output_path, source_chars, report)

    summary = [
        "章节流水线完成",
        f"源稿：{to_project_relative(input_path, project_root)}",
        f"输出：{to_project_relative(output_path, project_root)}",
        f"源稿正文：{source_chars}",
        f"验收结论：{report.get('overall')}",
        f"正文字数：{report.get('body_chars')}",
    ]
    if report.get("warnings"):
        summary.append("风险警告：")
        for item in report["warnings"]:
            summary.append(f"- {item}")
    if report.get("failures"):
        summary.append("阻塞问题：")
        for item in report["failures"]:
            summary.append(f"- {item}")
    if not args.skip_acceptance_log and acceptance_record is not None:
        summary.append(f"已写入验收记录：{to_project_relative(acceptance_record, project_root)}")
    if not args.skip_progress_log and progress_record is not None:
        summary.append(f"已写入进度记录：{to_project_relative(progress_record, project_root)}")
    print("\n".join(summary))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

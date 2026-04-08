#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


TITLE_RE = re.compile(r"^第([0-9一二三四五六七八九十百千零〇两]+)章\s+\S+")
RANGE_RE = re.compile(r"每章目标(?:字数)?[^0-9]{0,20}(\d+)\s*[—\-~至到]\s*(\d+)\s*字")
MIN_RE = re.compile(r"(?:每章最低(?:字数)?|最低(?:字数)?)[^0-9]{0,20}(?:不低于\s*)?(\d+)\s*字")
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
HTML_RE = re.compile(r"<[^>]+>")
BAD_CHAR_RE = re.compile(r"�")
SPACE_RE = re.compile(r"\s+")
FILE_CHAPTER_RE = re.compile(r"(?<!\d)(\d{1,4})(?:[_-]|$)")

CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
CHINESE_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
}


@dataclass
class RuleConfig:
    target_min: int = 3200
    target_max: int = 3800
    absolute_min: int = 3200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="章节硬规则与连续性校验脚本")
    parser.add_argument("--chapter", required=True, help="当前章节文件，支持 .docx/.md/.txt")
    parser.add_argument("--rules", action="append", default=[], help="规则文件，可重复传入")
    parser.add_argument("--outline", help="总目录或大纲文件")
    parser.add_argument("--previous-dir", help="上一章节目录，脚本会自动筛选当前章之前的文件")
    parser.add_argument("--previous", action="append", default=[], help="手动指定要比较的前文章节，可重复传入")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")
    parser.add_argument("--near-threshold", type=float, default=0.9, help="近重复判定阈值")
    parser.add_argument("--recent-window", type=int, default=6, help="上一章尾段与本章开头重叠检查段数")
    return parser.parse_args()


def read_text(path: Path) -> tuple[list[str], str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        paragraphs = read_docx_paragraphs(path)
    else:
        text = path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n")
        paragraphs = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^[#>*\-]+\s*", "", line)
            if line:
                paragraphs.append(line)
    raw = "\n".join(paragraphs)
    return paragraphs, raw


def read_docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        data = zf.read("word/document.xml")
    root = ET.fromstring(data)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for p in root.findall(".//w:body//w:p", ns):
        texts = []
        for node in p.findall(".//w:t", ns):
            texts.append(node.text or "")
        text = "".join(texts).replace("\xa0", " ").strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def normalize(text: str) -> str:
    return SPACE_RE.sub("", text)


def count_body_chars(paragraphs: list[str]) -> int:
    return len(normalize("".join(paragraphs)))


def chinese_to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    total = 0
    current = 0
    seen = False
    for ch in token:
        if ch in CHINESE_DIGITS:
            current = CHINESE_DIGITS[ch]
            seen = True
            continue
        unit = CHINESE_UNITS.get(ch)
        if unit is None:
            return None
        seen = True
        if current == 0:
            current = 1
        total += current * unit
        current = 0
    if not seen:
        return None
    return total + current


def int_to_chinese(num: int) -> str:
    if num <= 0:
        return str(num)
    digits = "零一二三四五六七八九"
    units = ["", "十", "百", "千"]
    parts = []
    zero_pending = False
    chars = list(str(num))
    length = len(chars)
    for idx, ch in enumerate(chars):
        digit = int(ch)
        pos = length - idx - 1
        if digit == 0:
            zero_pending = bool(parts)
            continue
        if zero_pending:
            parts.append("零")
            zero_pending = False
        if not (digit == 1 and pos == 1 and not parts):
            parts.append(digits[digit])
        parts.append(units[pos])
    return "".join(parts)


def detect_chapter_number(title: str, path: Path) -> int | None:
    match = TITLE_RE.match(title)
    if match:
        return chinese_to_int(match.group(1))
    file_match = FILE_CHAPTER_RE.search(path.stem)
    if file_match:
        return int(file_match.group(1))
    return None


def parse_rules(rule_paths: Iterable[Path]) -> RuleConfig:
    config = RuleConfig()
    range_found = False
    min_found = False
    for path in rule_paths:
        if not path.exists():
            continue
        paragraphs, _ = read_text(path)
        text = "\n".join(paragraphs)
        for match in RANGE_RE.finditer(text):
            range_found = True
            config.target_min = int(match.group(1))
            config.target_max = int(match.group(2))
        for match in MIN_RE.finditer(text):
            min_found = True
            config.absolute_min = int(match.group(1))
    if range_found and not min_found:
        config.absolute_min = config.target_min
    return config


def find_exact_duplicates(paragraphs: list[str], min_len: int = 25) -> list[dict[str, object]]:
    seen: dict[str, list[int]] = defaultdict(list)
    samples: dict[str, str] = {}
    for idx, para in enumerate(paragraphs, start=1):
        key = normalize(para)
        if len(key) < min_len:
            continue
        seen[key].append(idx)
        samples[key] = para
    duplicates = []
    for key, indexes in seen.items():
        if len(indexes) > 1:
            duplicates.append(
                {
                    "indexes": indexes,
                    "sample": samples[key],
                }
            )
    return duplicates


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def find_near_duplicates(
    paragraphs: list[str], threshold: float, min_len: int = 80, limit: int = 6
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for idx, para in enumerate(paragraphs):
        if len(normalize(para)) < min_len:
            continue
        for jdx in range(idx + 1, len(paragraphs)):
            other = paragraphs[jdx]
            if len(normalize(other)) < min_len:
                continue
            ratio = similarity(para, other)
            if ratio >= threshold:
                issues.append(
                    {
                        "left_index": idx + 1,
                        "right_index": jdx + 1,
                        "ratio": round(ratio, 3),
                        "left_sample": para,
                        "right_sample": other,
                    }
                )
                if len(issues) >= limit:
                    return issues
    return issues


def collect_previous_files(current_no: int | None, previous_dir: Path | None, explicit: list[Path]) -> list[Path]:
    files = list(explicit)
    if previous_dir and previous_dir.exists():
        candidates = sorted(
            [p for p in previous_dir.iterdir() if p.is_file() and p.suffix.lower() in {".docx", ".md", ".txt"}]
        )
        for path in candidates:
            file_no = detect_chapter_number(path.stem, path)
            if current_no is None or file_no is None:
                continue
            if file_no < current_no:
                files.append(path)
    deduped = []
    seen = set()
    for path in files:
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return sorted(deduped, key=lambda p: detect_chapter_number(p.stem, p) or 0)


def find_previous_overlaps(
    current_paragraphs: list[str],
    previous_files: list[Path],
    threshold: float,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object] | None]:
    exact_hits: list[dict[str, object]] = []
    near_hits: list[dict[str, object]] = []
    latest_prev_summary: dict[str, object] | None = None

    previous_maps: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
    previous_payloads: list[tuple[Path, list[str]]] = []

    for path in previous_files:
        paragraphs, _ = read_text(path)
        previous_payloads.append((path, paragraphs))
        for idx, para in enumerate(paragraphs, start=1):
            key = normalize(para)
            if len(key) < 25:
                continue
            previous_maps[key].append((path, idx, para))

    for idx, para in enumerate(current_paragraphs, start=1):
        key = normalize(para)
        if len(key) < 25:
            continue
        for path, prev_idx, sample in previous_maps.get(key, []):
            exact_hits.append(
                {
                    "current_index": idx,
                    "previous_file": str(path),
                    "previous_index": prev_idx,
                    "sample": sample,
                }
            )

    recent_previous = previous_payloads[-3:]
    for idx, para in enumerate(current_paragraphs, start=1):
        if len(normalize(para)) < 80:
            continue
        for path, paragraphs in recent_previous:
            for prev_idx, previous_para in enumerate(paragraphs, start=1):
                if len(normalize(previous_para)) < 80:
                    continue
                ratio = similarity(para, previous_para)
                if ratio >= threshold:
                    near_hits.append(
                        {
                            "current_index": idx,
                            "previous_file": str(path),
                            "previous_index": prev_idx,
                            "ratio": round(ratio, 3),
                            "current_sample": para,
                            "previous_sample": previous_para,
                        }
                    )
                    if len(near_hits) >= 8:
                        break
            if len(near_hits) >= 8:
                break
        if len(near_hits) >= 8:
            break

    if previous_payloads:
        latest_path, latest_paragraphs = previous_payloads[-1]
        latest_prev_summary = {
            "file": str(latest_path),
            "paragraphs": latest_paragraphs,
        }
    return exact_hits, near_hits, latest_prev_summary


def recent_recap_overlap(
    current_paragraphs: list[str], latest_previous: dict[str, object] | None, recent_window: int
) -> list[dict[str, object]]:
    if not latest_previous:
        return []
    previous_paragraphs = latest_previous["paragraphs"]
    current_window = current_paragraphs[:recent_window]
    previous_window = previous_paragraphs[-recent_window:]
    overlaps = []
    for idx, para in enumerate(current_window, start=1):
        best_ratio = 0.0
        best_prev_idx = None
        best_prev_sample = None
        for prev_offset, previous_para in enumerate(previous_window, start=max(1, len(previous_paragraphs) - recent_window + 1)):
            ratio = similarity(para, previous_para)
            if ratio > best_ratio:
                best_ratio = ratio
                best_prev_idx = prev_offset
                best_prev_sample = previous_para
        if best_ratio >= 0.78:
            overlaps.append(
                {
                    "current_index": idx,
                    "previous_file": latest_previous["file"],
                    "previous_index": best_prev_idx,
                    "ratio": round(best_ratio, 3),
                    "current_sample": para,
                    "previous_sample": best_prev_sample,
                }
            )
    return overlaps


def locate_outline_entry(outline_path: Path | None, chapter_no: int | None, title: str) -> list[str]:
    if outline_path is None or not outline_path.exists():
        return []
    paragraphs, _ = read_text(outline_path)
    if chapter_no is None:
        return [para for para in paragraphs if title in para][:3]
    patterns = [f"第{chapter_no}章", f"第{int_to_chinese(chapter_no)}章"]
    matched = [para for para in paragraphs if any(pattern in para for pattern in patterns)]
    return matched[:3]


def build_report(args: argparse.Namespace) -> dict[str, object]:
    chapter_path = Path(args.chapter)
    if not chapter_path.exists():
        raise FileNotFoundError(f"找不到章节文件: {chapter_path}")

    rule_paths = [Path(path) for path in args.rules]
    rules = parse_rules(rule_paths)
    paragraphs, raw_text = read_text(chapter_path)
    if not paragraphs:
        raise ValueError("章节内容为空，无法校验")

    title = paragraphs[0]
    body_paragraphs = paragraphs[1:]
    chapter_no = detect_chapter_number(title, chapter_path)
    body_chars = count_body_chars(body_paragraphs)

    title_ok = bool(TITLE_RE.match(title))
    links = URL_RE.findall(raw_text)
    html_hits = HTML_RE.findall(raw_text)
    bad_chars = BAD_CHAR_RE.findall(raw_text)
    exact_duplicates = find_exact_duplicates(body_paragraphs)
    near_duplicates = find_near_duplicates(body_paragraphs, args.near_threshold)

    previous_files = collect_previous_files(
        current_no=chapter_no,
        previous_dir=Path(args.previous_dir) if args.previous_dir else None,
        explicit=[Path(path) for path in args.previous],
    )
    prev_exact_hits, prev_near_hits, latest_previous = find_previous_overlaps(
        current_paragraphs=body_paragraphs,
        previous_files=previous_files,
        threshold=args.near_threshold,
    )
    recap_hits = recent_recap_overlap(body_paragraphs, latest_previous, args.recent_window)
    outline_entries = locate_outline_entry(Path(args.outline) if args.outline else None, chapter_no, title)

    paragraph_lengths = [len(normalize(para)) for para in body_paragraphs]
    long_paragraphs = [
        {"index": idx + 1, "chars": length, "sample": body_paragraphs[idx]}
        for idx, length in enumerate(paragraph_lengths)
        if length >= 180
    ][:8]

    failures = []
    warnings = []
    passes = []

    if title_ok:
        passes.append("标题格式符合 `第X章 XXXXX`")
    else:
        failures.append("标题格式不符合 `第X章 XXXXX`")

    if body_chars < rules.absolute_min:
        failures.append(f"正文字数 {body_chars}，低于最低要求 {rules.absolute_min}")
    elif body_chars > rules.target_max:
        failures.append(f"正文字数 {body_chars}，超出目标上限 {rules.target_max}")
    elif body_chars < rules.target_min:
        warnings.append(f"正文字数 {body_chars}，高于最低要求但低于目标区间 {rules.target_min}-{rules.target_max}")
    else:
        passes.append(f"正文字数 {body_chars}，位于目标区间 {rules.target_min}-{rules.target_max}")

    if links:
        failures.append(f"检测到外链痕迹 {len(links)} 处")
    else:
        passes.append("未发现外链")

    if html_hits:
        failures.append(f"检测到 HTML 痕迹 {len(html_hits)} 处")
    else:
        passes.append("未发现 HTML 痕迹")

    if bad_chars:
        failures.append(f"检测到乱码替代字符 {len(bad_chars)} 处")
    else:
        passes.append("未发现乱码替代字符")

    if exact_duplicates:
        failures.append(f"当前章节内存在 {len(exact_duplicates)} 组重复段落")
    else:
        passes.append("当前章节内未发现重复段落")

    if near_duplicates:
        warnings.append(f"当前章节内存在 {len(near_duplicates)} 组高相似重复段落")
    else:
        passes.append("当前章节内未发现高相似重复段落")

    if prev_exact_hits:
        failures.append(f"与前文章节存在 {len(prev_exact_hits)} 处完全重复段落")
    else:
        passes.append("未发现与前文章节完全重复的段落")

    if prev_near_hits:
        warnings.append(f"与前文章节存在 {len(prev_near_hits)} 处高相似重复段落")

    if recap_hits:
        warnings.append(f"本章开头与上一章尾段存在 {len(recap_hits)} 处高相似复述")

    if long_paragraphs:
        warnings.append(f"检测到 {len(long_paragraphs)} 个偏长段落，建议复核拆段")
    else:
        passes.append("未发现明显超长段落")

    if outline_entries:
        passes.append("已在大纲/目录中定位到当前章节条目")
    else:
        warnings.append("未在大纲/目录中定位到当前章节条目，需人工确认是否错位")

    numbering = {"current_chapter": chapter_no, "previous_last": None, "continuous": None}
    if previous_files:
        previous_last = previous_files[-1]
        previous_last_no = detect_chapter_number(previous_last.stem, previous_last)
        numbering["previous_last"] = previous_last_no
        if chapter_no is not None and previous_last_no is not None:
            numbering["continuous"] = previous_last_no == chapter_no - 1
            if numbering["continuous"]:
                passes.append("章节编号与上一章连续")
            else:
                warnings.append(f"章节编号可能不连续：上一章识别为 {previous_last_no}，当前章识别为 {chapter_no}")

    overall = "通过"
    if failures:
        overall = "不通过"
    elif warnings:
        overall = "警告"

    return {
        "overall": overall,
        "file": str(chapter_path),
        "title": title,
        "chapter_number": chapter_no,
        "body_chars": body_chars,
        "rules": {
            "target_min": rules.target_min,
            "target_max": rules.target_max,
            "absolute_min": rules.absolute_min,
        },
        "passes": passes,
        "warnings": warnings,
        "failures": failures,
        "outline_entries": outline_entries,
        "numbering": numbering,
        "evidence": {
            "exact_duplicates": exact_duplicates,
            "near_duplicates": near_duplicates,
            "previous_exact_hits": prev_exact_hits[:8],
            "previous_near_hits": prev_near_hits[:8],
            "recent_recap_hits": recap_hits[:8],
            "long_paragraphs": long_paragraphs,
        },
    }


def render_text(report: dict[str, object]) -> str:
    lines = []
    lines.append("章节验收报告")
    lines.append(f"结论：{report['overall']}")
    lines.append(f"文件：{report['file']}")
    lines.append(f"标题：{report['title']}")
    lines.append(f"章节号：{report['chapter_number']}")
    lines.append(f"正文字数：{report['body_chars']}")
    rules = report["rules"]
    lines.append(
        f"规则：目标 {rules['target_min']}-{rules['target_max']}，最低 {rules['absolute_min']}"
    )

    if report["outline_entries"]:
        lines.append("匹配到的大纲条目：")
        for entry in report["outline_entries"]:
            lines.append(f"- {entry}")

    for label in ("failures", "warnings", "passes"):
        items = report[label]
        if not items:
            continue
        title = {
            "failures": "阻塞问题",
            "warnings": "风险警告",
            "passes": "通过项",
        }[label]
        lines.append(f"{title}：")
        for item in items:
            lines.append(f"- {item}")

    evidence = report["evidence"]
    if evidence["exact_duplicates"]:
        lines.append("当前章内重复段落证据：")
        for item in evidence["exact_duplicates"][:5]:
            lines.append(f"- 段落 {item['indexes']}：{item['sample'][:80]}")

    if evidence["previous_exact_hits"]:
        lines.append("与前文章节完全重复证据：")
        for item in evidence["previous_exact_hits"][:5]:
            lines.append(
                f"- 当前第{item['current_index']}段 与 {item['previous_file']} 第{item['previous_index']}段重复："
                f"{item['sample'][:80]}"
            )

    if evidence["recent_recap_hits"]:
        lines.append("开头复述上一章尾段证据：")
        for item in evidence["recent_recap_hits"][:5]:
            lines.append(
                f"- 当前第{item['current_index']}段 与上一章第{item['previous_index']}段相似度 {item['ratio']}"
            )

    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    try:
        report = build_report(args)
    except Exception as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))

    return 0 if report["overall"] != "不通过" else 2


if __name__ == "__main__":
    sys.exit(main())

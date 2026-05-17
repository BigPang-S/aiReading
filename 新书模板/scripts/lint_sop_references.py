#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re


DEFAULT_EXCLUDES = {"小说正文", "归档", ".git", "__pycache__"}
BAD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("日常流程不应默认读取总目录", re.compile(r"(日常|每章|写章|连载|验收).{0,30}默认(?!不).{0,30}(?<!不)(读取|回读).{0,30}总目录")),
    ("日常流程不应默认读取进度记录", re.compile(r"(日常|每章|写章|连载|验收).{0,30}默认(?!不).{0,30}(?<!不)(读取|回读).{0,30}进度记录")),
    ("日常流程不应默认读取验收记录", re.compile(r"(日常|每章|写章|连载|验收).{0,30}默认(?!不).{0,30}(?<!不)(读取|回读).{0,30}章节验收记录")),
    ("日常流程不应默认读取完整 skill", re.compile(r"(日常|每章|写章|连载).{0,40}默认(?!不).{0,20}(?<!不)(读取|打开).{0,20}完整\s*skill")),
    ("不要把三卡和上下文包并列投喂", re.compile(r"当前有效规则卡.{0,40}当前卷.{0,40}当前章.{0,40}当前章上下文包")),
]
RULE_DUP_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("重复字数规则", re.compile(r"3200.{0,12}3800|最低.{0,8}3200")),
    ("重复标题规则", re.compile(r"第X章\s+XXXXX")),
    ("重复排版规则", re.compile(r"黑体三号|宋体小四|29\s*磅")),
]
ALLOW_RULE_FILES = {
    "当前有效规则卡.md",
    "08_Word排版规范.md",
    "chapter_guard.py",
}


def should_skip(path: Path) -> bool:
    return any(part in DEFAULT_EXCLUDES for part in path.parts) or path.suffix != ".md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 SOP 文档是否存在低 token 互斥规则冲突")
    parser.add_argument("--root", default=".", help="检查根目录，默认当前目录")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    warnings: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or should_skip(path.relative_to(root)):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(root)
        for label, pattern in BAD_PATTERNS:
            if pattern.search(text):
                warnings.append(f"[冲突] {rel}: {label}")
        if path.name not in ALLOW_RULE_FILES:
            for label, pattern in RULE_DUP_PATTERNS:
                if pattern.search(text):
                    warnings.append(f"[重复硬规则] {rel}: {label}，请改为引用 当前有效规则卡.md")

    if warnings:
        print("\n".join(warnings))
        return 1
    print("SOP 引用检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

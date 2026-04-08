#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


IGNORE_NAMES = {".DS_Store", "__pycache__"}


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(*IGNORE_NAMES, "*.pyc"),
        dirs_exist_ok=True,
    )


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> int:
    script_path = Path(__file__).resolve()
    template_root = script_path.parent.parent
    repo_root = template_root.parent

    target_root = template_root / "SOP资料"
    docs_dir = target_root / "说明文档"
    skills_dir = target_root / "skills"
    workflows_dir = target_root / "workflows"

    clean_dir(target_root)
    docs_dir.mkdir(parents=True, exist_ok=True)

    for file_name in ["总览说明.md", "给下一个工具的接管说明.md"]:
        copy_file(repo_root / file_name, docs_dir / file_name)

    copy_tree(repo_root / "skills", skills_dir)
    copy_tree(repo_root / "workflows", workflows_dir)

    print("已同步以下内容到新书模板/SOP资料：")
    print(f"- 说明文档: {docs_dir}")
    print(f"- skills: {skills_dir}")
    print(f"- workflows: {workflows_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

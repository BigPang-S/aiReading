#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


IGNORE_NAMES = {".DS_Store", "__pycache__"}
MANIFEST_NAME = ".sync_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步上级 SOP 资料到当前项目，默认保留本地增量")
    parser.add_argument(
        "--source-root",
        help="SOP 源目录；默认取当前模板的上级目录，若上级目录没有 SOP 源则安全跳过",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制覆盖与上级版本冲突的已有文件",
    )
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def should_ignore(path: Path) -> bool:
    return path.name in IGNORE_NAMES or path.suffix == ".pyc"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def save_manifest(path: Path, manifest: dict[str, str]) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(dict(sorted(manifest.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_file(src: Path, dst: Path) -> None:
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)


def iter_tree_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*") if path.is_file() and not should_ignore(path)
    )


def has_sop_source(root: Path) -> bool:
    return all(
        [
            (root / "小说SOP最终流程.md").exists(),
            (root / "skills").is_dir(),
            (root / "workflows").is_dir(),
        ]
    )


def sync_file(
    src: Path,
    dst: Path,
    key: str,
    previous_manifest: dict[str, str],
    next_manifest: dict[str, str],
    *,
    force: bool,
) -> str:
    src_hash = file_sha256(src)
    previous_hash = previous_manifest.get(key)

    if not dst.exists():
        copy_file(src, dst)
        next_manifest[key] = src_hash
        return "copied"

    dst_hash = file_sha256(dst)
    if dst_hash == src_hash:
        next_manifest[key] = src_hash
        return "unchanged"

    if force or (previous_hash and dst_hash == previous_hash):
        copy_file(src, dst)
        next_manifest[key] = src_hash
        return "updated"

    if previous_hash:
        next_manifest[key] = previous_hash
    return "conflict"


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    template_root = script_path.parent.parent
    default_source_root = template_root.parent
    source_root = (
        Path(args.source_root).expanduser().resolve()
        if args.source_root
        else default_source_root
    )

    if not has_sop_source(source_root):
        if args.source_root:
            print(f"指定的 SOP 源目录不完整：{source_root}")
            print("需要同时包含：小说SOP最终流程.md、skills/、workflows/")
            return 2
        print("未找到上级 SOP 源目录，已跳过同步。")
        print("当前 aiReading 根目录默认只保留入口和 `新书模板/`；模板内置的 `SOP资料/` 已可直接使用。")
        print("如果你另有 SOP 源目录，可执行：python3 scripts/sync_sop_assets.py --source-root <目录>")
        return 0

    target_root = template_root / "SOP资料"
    skills_dir = target_root / "skills"
    workflows_dir = target_root / "workflows"
    manifest_path = target_root / MANIFEST_NAME

    ensure_dir(skills_dir)
    ensure_dir(workflows_dir)

    previous_manifest = load_manifest(manifest_path)
    next_manifest: dict[str, str] = {}
    copied: list[str] = []
    updated: list[str] = []
    conflicts: list[str] = []

    def apply_status(status: str, key: str) -> None:
        if status == "copied":
            copied.append(key)
        elif status == "updated":
            updated.append(key)
        elif status == "conflict":
            conflicts.append(key)

    status = sync_file(
        source_root / "小说SOP最终流程.md",
        template_root / "小说SOP最终流程.md",
        "小说SOP最终流程.md",
        previous_manifest,
        next_manifest,
        force=args.force,
    )
    apply_status(status, "小说SOP最终流程.md")

    for src_root, dst_root, prefix in [
        (source_root / "skills", skills_dir, "skills"),
        (source_root / "workflows", workflows_dir, "workflows"),
    ]:
        for src in iter_tree_files(src_root):
            relative = src.relative_to(src_root)
            dst = dst_root / relative
            key = str(Path(prefix) / relative)
            status = sync_file(
                src,
                dst,
                key,
                previous_manifest,
                next_manifest,
                force=args.force,
            )
            apply_status(status, key)

    save_manifest(manifest_path, next_manifest)

    print("已同步上级 SOP 资料到当前项目的 `SOP资料/`：")
    print(f"- 最终流程: {template_root / '小说SOP最终流程.md'}")
    print(f"- skills: {skills_dir}")
    print(f"- workflows: {workflows_dir}")
    print(f"- 新增文件: {len(copied)}")
    print(f"- 更新文件: {len(updated)}")
    if conflicts:
        print(f"- 保留本地版本: {len(conflicts)}")
        for key in conflicts[:12]:
            print(f"  - {key}")
        if len(conflicts) > 12:
            print(f"  - 其余 {len(conflicts) - 12} 项已省略")
        if not args.force:
            print("- 如需强制覆盖冲突文件，可追加 `--force`")
    else:
        print("- 保留本地版本: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

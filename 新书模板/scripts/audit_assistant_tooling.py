#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys


HOME = Path.home()
CLAUDE_MEM_SETTINGS = HOME / ".claude-mem" / "settings.json"
CLAUDE_MEM_DB = HOME / ".claude-mem" / "claude-mem.db"
RTK_CONFIG = HOME / "Library" / "Application Support" / "rtk" / "config.toml"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_excluded_projects(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def load_rtk_config_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def query_projects(db_path: Path) -> list[tuple[str, int]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "select project, count(*) as n from sdk_sessions group by project order by n desc, project asc"
        ).fetchall()
    return [(str(project), int(count)) for project, count in rows]


def status_line(level: str, message: str) -> str:
    return f"[{level}] {message}"


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    if not CLAUDE_MEM_SETTINGS.exists():
        errors.append(f"未找到 Claude-Mem 设置文件：{CLAUDE_MEM_SETTINGS}")
    else:
        settings = load_json(CLAUDE_MEM_SETTINGS)
        excluded = parse_excluded_projects(settings.get("CLAUDE_MEM_EXCLUDED_PROJECTS", ""))
        recommended = {HOME.name, "thedotmack"}
        missing = sorted(item for item in recommended if item not in excluded)
        if missing:
            warnings.append(f"Claude-Mem 未排除这些泛项目名：{', '.join(missing)}")
        else:
            infos.append(f"Claude-Mem 已排除泛项目名：{', '.join(sorted(recommended))}")

        obs = settings.get("CLAUDE_MEM_CONTEXT_OBSERVATIONS")
        sessions = settings.get("CLAUDE_MEM_CONTEXT_SESSION_COUNT")
        terminal_output = settings.get("CLAUDE_MEM_CONTEXT_SHOW_TERMINAL_OUTPUT")
        if obs != "20":
            warnings.append(f"CLAUDE_MEM_CONTEXT_OBSERVATIONS 当前为 {obs}，推荐 20")
        else:
            infos.append("Claude-Mem observations 注入预算为 20")
        if sessions != "3":
            warnings.append(f"CLAUDE_MEM_CONTEXT_SESSION_COUNT 当前为 {sessions}，推荐 3")
        else:
            infos.append("Claude-Mem session 注入预算为 3")
        if terminal_output != "false":
            warnings.append(f"CLAUDE_MEM_CONTEXT_SHOW_TERMINAL_OUTPUT 当前为 {terminal_output}，推荐 false")
        else:
            infos.append("Claude-Mem 已关闭 terminal output 注入")

    if CLAUDE_MEM_DB.exists():
        projects = query_projects(CLAUDE_MEM_DB)
        infos.append("Claude-Mem 当前数据库项目分布：")
        for name, count in projects:
            infos.append(f"  - {name}: {count}")
        if CLAUDE_MEM_SETTINGS.exists():
            present_projects = {name for name, _ in projects}
            stale = sorted(item for item in excluded if item in present_projects)
            if stale:
                warnings.append(f"Claude-Mem 数据库里仍有这些已排除项目的旧记录：{', '.join(stale)}")
    else:
        warnings.append(f"未找到 Claude-Mem 数据库：{CLAUDE_MEM_DB}")

    if not RTK_CONFIG.exists():
        errors.append(f"未找到 RTK 配置文件：{RTK_CONFIG}")
    else:
        text = load_rtk_config_text(RTK_CONFIG)
        if "[telemetry]" not in text:
            warnings.append("RTK 配置里未找到 telemetry 段")
        if "enabled = false" not in text:
            warnings.append("RTK telemetry 仍未关闭")
        else:
            infos.append("RTK telemetry 已关闭")

    for item in infos:
        print(status_line("INFO", item))
    for item in warnings:
        print(status_line("WARN", item))
    for item in errors:
        print(status_line("ERROR", item), file=sys.stderr)

    if errors:
        return 2
    if warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

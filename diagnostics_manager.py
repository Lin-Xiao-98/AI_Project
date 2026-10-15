"""生成不包含私密内容和密钥值的本地诊断报告。"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

from conversation_manager import DEFAULT_DATABASE, PROJECT_DIR
from guardian_control import read_status
from secret_store import get_secret
from usage_manager import UsageManager

DIAGNOSTICS_DIR = PROJECT_DIR / "data" / "diagnostics"
SAFE_TABLES = (
    "sessions",
    "messages",
    "tasks",
    "reminders",
    "knowledge_documents",
    "knowledge_chunks",
    "pending_actions",
    "api_usage",
)
DEPENDENCIES = ("openai", "python-dotenv", "pypdf", "python-docx", "openpyxl")


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _database_status(database: Path) -> dict:
    if not database.exists():
        return {"exists": False, "integrity": "missing", "counts": {}}
    try:
        with closing(sqlite3.connect(database, timeout=10)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            available = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            counts = {
                table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in SAFE_TABLES
                if table in available
            }
        return {"exists": True, "integrity": integrity, "counts": counts}
    except sqlite3.Error as error:
        return {"exists": True, "integrity": "error", "error": str(error), "counts": {}}


def _git_status(project_dir: Path) -> dict:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=project_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        changes = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.splitlines()
        return {"available": True, "branch": branch, "changed_files": len(changes)}
    except (OSError, subprocess.SubprocessError):
        return {"available": False}


def _dependency_versions() -> dict[str, str]:
    versions = {}
    for package in DEPENDENCIES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return versions


def _secret_ready(name: str, env_name: str) -> bool:
    try:
        return bool(get_secret(name, env_name))
    except (OSError, RuntimeError, ValueError):
        return False


def create_diagnostic_report(
    output_directory=DIAGNOSTICS_DIR,
    database=DEFAULT_DATABASE,
    project_dir=PROJECT_DIR,
) -> Path:
    """写出可安全分享的诊断摘要，不保存聊天、记忆或密钥内容。"""
    output_directory = Path(output_directory)
    database = Path(database)
    project_dir = Path(project_dir)
    output_directory.mkdir(parents=True, exist_ok=True)
    usage = UsageManager(database).summary()
    disk = shutil.disk_usage(project_dir)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "privacy": "不含密钥值、聊天正文、记忆正文和资料正文",
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "executable": sys.executable,
        },
        "guardian": read_status(),
        "secrets_ready": {
            "openai": _secret_ready("openai_api_key", "OPENAI_API_KEY"),
            "weixin": _secret_ready("weixin_bot_token", "WEIXIN_BOT_TOKEN"),
        },
        "api_usage": usage,
        "database": _database_status(database),
        "storage": {
            "project_bytes": _directory_size(project_dir),
            "data_bytes": _directory_size(project_dir / "data"),
            "backups_bytes": _directory_size(project_dir / "backups"),
            "drive_free_bytes": disk.free,
        },
        "dependencies": _dependency_versions(),
        "git": _git_status(project_dir),
    }
    path = output_directory / datetime.now().strftime("diagnostic_%Y%m%d_%H%M%S.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

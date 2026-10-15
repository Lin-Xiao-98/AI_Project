"""把助手个人数据导出为可迁移的 ZIP，不包含 API 或微信密钥。"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from conversation_manager import DEFAULT_DATABASE, PROJECT_DIR
from memory_manager import MEMORY_FILE

EXPORT_DIR = PROJECT_DIR / "exports"
EXPORT_TABLES = (
    "sessions",
    "messages",
    "tasks",
    "reminders",
    "knowledge_documents",
    "knowledge_chunks",
    "pending_actions",
    "proactive_state",
    "api_usage",
)


def _database_export(database: Path) -> dict[str, list[dict]]:
    if not database.exists():
        return {}
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        available = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        return {
            table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
            for table in EXPORT_TABLES
            if table in available
        }


def export_personal_data(
    output_directory=EXPORT_DIR,
    database=DEFAULT_DATABASE,
    memory_file=MEMORY_FILE,
) -> Path:
    """导出用户数据；明确排除 secrets.json、.env 和微信登录令牌。"""
    output_directory = Path(output_directory)
    database = Path(database)
    memory_file = Path(memory_file)
    output_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = output_directory / f"assistant_export_{stamp}.zip"
    payload = {
        "format_version": 1,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "notice": "个人数据导出；不包含 API 密钥、微信令牌和 .env。",
        "database": _database_export(database),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="assistant_export_", suffix=".tmp", dir=output_directory
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(
            temporary_name, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                "personal_data.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
            if memory_file.exists():
                archive.write(memory_file, "memory.json")
            metadata = memory_file.with_name("memory_metadata.json")
            if metadata.exists():
                archive.write(metadata, "memory_metadata.json")
            archive.writestr(
                "README.txt",
                "此压缩包是小林 AI 助手的个人数据副本。请像保护聊天记录一样妥善保管。\n"
                "它不包含 OpenAI API Key、微信令牌或 .env。\n",
            )
        Path(temporary_name).replace(target)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return target

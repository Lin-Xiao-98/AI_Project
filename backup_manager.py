import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from conversation_manager import DEFAULT_DATABASE, PROJECT_DIR
from memory_manager import MEMORY_FILE

BACKUP_DIR = PROJECT_DIR / "backups"


def create_backup(
    memory_file=MEMORY_FILE,
    database_file=DEFAULT_DATABASE,
    backup_directory=BACKUP_DIR,
):
    """备份长期记忆和本地数据库；永远不包含 .env。"""
    memory_file = Path(memory_file)
    database_file = Path(database_file)
    backup_directory = Path(backup_directory)
    backup_directory.mkdir(parents=True, exist_ok=True)

    sources = []
    database_snapshot = None
    if memory_file.exists():
        sources.append((memory_file, "memory.json"))
    if database_file.exists():
        snapshot_descriptor, snapshot_name = tempfile.mkstemp(
            prefix="assistant_snapshot_", suffix=".db", dir=backup_directory
        )
        os.close(snapshot_descriptor)
        database_snapshot = Path(snapshot_name)
        try:
            with closing(sqlite3.connect(database_file)) as source_connection:
                with closing(sqlite3.connect(database_snapshot)) as snapshot_connection:
                    source_connection.backup(snapshot_connection)
                    snapshot_connection.commit()
                    result = snapshot_connection.execute("PRAGMA integrity_check").fetchone()
                    if not result or result[0] != "ok":
                        raise RuntimeError("数据库备份完整性检查失败")
        except Exception:
            database_snapshot.unlink(missing_ok=True)
            raise
        sources.append((database_snapshot, "assistant.db"))
    if not sources:
        raise ValueError("没有找到可备份的记忆或数据库文件")

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    destination = backup_directory / f"ai_assistant_backup_{timestamp}.zip"
    descriptor, temp_name = tempfile.mkstemp(
        prefix="backup_", suffix=".tmp", dir=backup_directory
    )
    os.close(descriptor)

    try:
        with zipfile.ZipFile(
            temp_name, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for source, archive_name in sources:
                archive.write(source, arcname=archive_name)
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    finally:
        if database_snapshot is not None:
            database_snapshot.unlink(missing_ok=True)
    return destination

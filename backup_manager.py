import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from conversation_manager import DEFAULT_DATABASE, PROJECT_DIR
from memory_manager import MEMORY_FILE

BACKUP_DIR = PROJECT_DIR / "backups"


def create_backup(
    memory_file=MEMORY_FILE,
    database_file=DEFAULT_DATABASE,
    backup_directory=BACKUP_DIR,
    metadata_file=None,
):
    """备份长期记忆和本地数据库；永远不包含 .env。"""
    memory_file = Path(memory_file)
    database_file = Path(database_file)
    backup_directory = Path(backup_directory)
    backup_directory.mkdir(parents=True, exist_ok=True)
    metadata_file = Path(metadata_file) if metadata_file else memory_file.with_name(
        "memory_metadata.json"
    )

    sources = []
    database_snapshot = None
    if memory_file.exists():
        sources.append((memory_file, "memory.json"))
    if metadata_file.exists():
        sources.append((metadata_file, "memory_metadata.json"))
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


def prune_backups(
    backup_directory=BACKUP_DIR,
    keep: int = 14,
    max_age_days: int = 30,
):
    """保留最近若干份，并清理超过期限的旧备份。"""
    backup_directory = Path(backup_directory)
    if not backup_directory.exists():
        return []
    if keep < 1 or max_age_days < 1:
        raise ValueError("备份保留数量和天数必须大于 0。")
    backups = sorted(
        backup_directory.glob("ai_assistant_backup_*.zip"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    removed = []
    for index, path in enumerate(backups):
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if index >= keep and modified < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def create_backup_with_retention(
    memory_file=MEMORY_FILE,
    database_file=DEFAULT_DATABASE,
    backup_directory=BACKUP_DIR,
    keep: int = 14,
    max_age_days: int = 30,
):
    destination = create_backup(memory_file, database_file, backup_directory)
    prune_backups(backup_directory, keep, max_age_days)
    return destination


def restore_backup(
    backup_file,
    memory_file=MEMORY_FILE,
    database_file=DEFAULT_DATABASE,
    backup_directory=BACKUP_DIR,
    metadata_file=None,
):
    """校验备份后恢复；恢复前自动再备份一次当前数据。"""
    backup_file = Path(backup_file).expanduser().resolve()
    if not backup_file.is_file() or backup_file.suffix.lower() != ".zip":
        raise ValueError("请选择有效的 ZIP 备份文件。")
    memory_file = Path(memory_file)
    database_file = Path(database_file)
    metadata_file = Path(metadata_file) if metadata_file else memory_file.with_name(
        "memory_metadata.json"
    )
    backup_directory = Path(backup_directory)
    backup_directory.mkdir(parents=True, exist_ok=True)
    allowed = {"memory.json", "memory_metadata.json", "assistant.db"}
    with zipfile.ZipFile(backup_file) as archive:
        names = set(archive.namelist())
        if not names or not names.issubset(allowed):
            raise ValueError("备份包含未知文件，已拒绝恢复。")
        with tempfile.TemporaryDirectory(dir=backup_directory) as folder:
            temp_root = Path(folder)
            if "memory.json" in names:
                restored_memory = temp_root / "memory.json"
                restored_memory.write_bytes(archive.read("memory.json"))
                data = json.loads(restored_memory.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("备份中的长期记忆格式错误。")
            if "assistant.db" in names:
                restored_database = temp_root / "assistant.db"
                restored_database.write_bytes(archive.read("assistant.db"))
                with closing(sqlite3.connect(restored_database)) as connection:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                    if not result or result[0] != "ok":
                        raise ValueError("备份中的数据库完整性检查失败。")
            if "memory_metadata.json" in names:
                restored_metadata = temp_root / "memory_metadata.json"
                restored_metadata.write_bytes(archive.read("memory_metadata.json"))
                metadata = json.loads(restored_metadata.read_text(encoding="utf-8"))
                if not isinstance(metadata, dict):
                    raise ValueError("备份中的临时记忆元数据格式错误。")

            safety_backup = create_backup_with_retention(
                memory_file, database_file, backup_directory
            )
            if "memory.json" in names:
                memory_file.parent.mkdir(parents=True, exist_ok=True)
                os.replace(restored_memory, memory_file)
            if "assistant.db" in names:
                database_file.parent.mkdir(parents=True, exist_ok=True)
                os.replace(restored_database, database_file)
            if "memory_metadata.json" in names:
                metadata_file.parent.mkdir(parents=True, exist_ok=True)
                os.replace(restored_metadata, metadata_file)
            elif "memory.json" in names:
                metadata_file.unlink(missing_ok=True)
    return safety_backup

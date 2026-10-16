import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from conversation_manager import DEFAULT_DATABASE, PROJECT_DIR

WORKSPACE_DIR = PROJECT_DIR / "workspace"
MAX_CONTENT_BYTES = 100_000
ALLOWED_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".py",
    ".html",
    ".css",
    ".js",
}
BLOCKED_MANAGED_PARTS = {
    ".git",
    ".env",
    "venv",
    "__pycache__",
    "appdata",
    "windows",
    "program files",
    "program files (x86)",
}


def _default_managed_roots():
    home = Path.home()
    candidates = [Path("D:/Workspace"), home / "Desktop", home / "Documents", home / "Downloads"]
    return tuple(path.resolve() for path in candidates if path.exists())


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ActionManager:
    """保存并执行需要用户明确确认的本地动作。"""

    def __init__(
        self,
        database_path=DEFAULT_DATABASE,
        workspace_directory=WORKSPACE_DIR,
        managed_roots=None,
    ):
        self.database_path = Path(database_path)
        self.workspace_directory = Path(workspace_directory).resolve()
        self.managed_roots = tuple(
            Path(path).resolve() for path in (managed_roots or _default_managed_roots())
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialise(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected')),
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                CREATE INDEX IF NOT EXISTS pending_actions_status_created
                ON pending_actions(status, created_at);
                """
            )

    def _safe_workspace_path(self, relative_path):
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("文件路径不能为空")

        relative = Path(relative_path.strip())
        if relative.is_absolute():
            raise ValueError("只允许使用 workspace 内的相对路径")
        if any(part.startswith(".") for part in relative.parts):
            raise ValueError("不允许隐藏路径或上级目录")

        target = (self.workspace_directory / relative).resolve()
        try:
            target.relative_to(self.workspace_directory)
        except ValueError as error:
            raise ValueError("文件路径超出了 workspace 目录") from error

        if target.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError("不支持这种文件类型")
        return target

    def prepare_file_creation(self, relative_path, content):
        target = self._safe_workspace_path(relative_path)
        if not isinstance(content, str) or not content:
            raise ValueError("文件内容不能为空")
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ValueError("文件内容超过 100 KB")
        if target.exists():
            raise ValueError("目标文件已存在；当前版本禁止覆盖")

        action_id = uuid.uuid4().hex[:12]
        relative = target.relative_to(self.workspace_directory)
        payload = {"path": relative.as_posix(), "content": content}
        summary = f"新建 workspace/{relative.as_posix()}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pending_actions
                    (id, action_type, summary, payload, created_at)
                VALUES (?, 'create_file', ?, ?, ?)
                """,
                (action_id, summary, json.dumps(payload, ensure_ascii=False), _utc_now()),
            )
        return {"action_id": action_id, "summary": summary, "status": "pending"}

    def _safe_managed_path(self, value, must_exist=False):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("文件路径不能为空")
        target = Path(value.strip()).expanduser().resolve()
        managed_root = next(
            (
                root
                for root in self.managed_roots
                if target == root or root in target.parents
            ),
            None,
        )
        if managed_root is None:
            raise ValueError("文件路径不在授权整理目录中")
        relative_parts = target.relative_to(managed_root).parts
        if any(
            part.startswith(".") or part.casefold() in BLOCKED_MANAGED_PARTS
            for part in relative_parts
        ):
            raise ValueError("这个路径包含受保护目录")
        if must_exist and not target.is_file():
            raise ValueError("源文件不存在或不是普通文件")
        return target

    def prepare_file_move(self, source_path, destination_path):
        source = self._safe_managed_path(source_path, must_exist=True)
        destination = self._safe_managed_path(destination_path)
        if source.drive.casefold() != destination.drive.casefold():
            raise ValueError("当前版本只允许在同一个磁盘内移动文件")
        if destination.exists():
            raise ValueError("目标文件已经存在，拒绝覆盖")
        if not destination.parent.is_dir():
            raise ValueError("目标文件夹不存在")
        stat = source.stat()
        action_id = uuid.uuid4().hex[:12]
        payload = {
            "source": str(source),
            "destination": str(destination),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        summary = f"移动文件：{source} → {destination}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pending_actions
                    (id, action_type, summary, payload, created_at)
                VALUES (?, 'move_file', ?, ?, ?)
                """,
                (action_id, summary, json.dumps(payload, ensure_ascii=False), _utc_now()),
            )
        return {"action_id": action_id, "summary": summary, "status": "pending"}

    def list_pending(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, action_type, summary, created_at
                FROM pending_actions
                WHERE status = 'pending'
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def approve(self, action_id):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT action_type, payload, status
                FROM pending_actions
                WHERE id = ?
                """,
                (action_id,),
            ).fetchone()
            if row is None:
                raise ValueError("找不到这个待执行动作")
            if row["status"] != "pending":
                raise ValueError("这个动作已经处理过了")
            payload = json.loads(row["payload"])
            if row["action_type"] == "create_file":
                target = self._safe_workspace_path(payload["path"])
                if target.exists():
                    raise ValueError("目标文件已经存在，拒绝覆盖")

                target.parent.mkdir(parents=True, exist_ok=True)
                descriptor = None
                try:
                    descriptor = os.open(
                        target,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                    )
                    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                        descriptor = None
                        file.write(payload["content"])
                except FileExistsError as error:
                    raise ValueError("目标文件已经存在，拒绝覆盖") from error
                except Exception:
                    if descriptor is not None:
                        os.close(descriptor)
                    try:
                        os.unlink(target)
                    except FileNotFoundError:
                        pass
                    raise
            elif row["action_type"] == "move_file":
                source = self._safe_managed_path(payload["source"], must_exist=True)
                target = self._safe_managed_path(payload["destination"])
                current = source.stat()
                if current.st_size != payload["size"] or current.st_mtime_ns != payload["mtime_ns"]:
                    raise ValueError("源文件在审批期间发生变化，已停止移动")
                if target.exists():
                    raise ValueError("目标文件已经存在，拒绝覆盖")
                if not target.parent.is_dir():
                    raise ValueError("目标文件夹不存在")
                try:
                    source.rename(target)
                except FileExistsError as error:
                    raise ValueError("目标文件已经存在，拒绝覆盖") from error
            else:
                raise ValueError("不支持的动作类型")

            connection.execute(
                """
                UPDATE pending_actions
                SET status = 'approved', resolved_at = ?
                WHERE id = ?
                """,
                (_utc_now(), action_id),
            )
        return target

    def reject(self, action_id):
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE pending_actions
                SET status = 'rejected', resolved_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (_utc_now(), action_id),
            )
            return cursor.rowcount == 1

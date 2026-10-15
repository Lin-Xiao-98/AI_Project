import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from conversation_manager import DEFAULT_DATABASE


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskManager:
    """管理保存在本机数据库中的简单任务清单。"""

    def __init__(self, database_path=DEFAULT_DATABASE):
        self.database_path = Path(database_path)
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
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'done')),
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS tasks_status_id
                ON tasks(status, id);
                """
            )

    def add_task(self, title):
        if not isinstance(title, str) or not title.strip():
            raise ValueError("任务内容不能为空")

        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO tasks (title, created_at) VALUES (?, ?)",
                (title.strip(), _utc_now()),
            )
            return cursor.lastrowid

    def list_tasks(self, include_done=False):
        query = "SELECT id, title, status, created_at, completed_at FROM tasks"
        parameters = ()
        if not include_done:
            query += " WHERE status = ?"
            parameters = ("pending",)
        query += " ORDER BY status DESC, id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def complete_task(self, task_id):
        task_id = self._validate_task_id(task_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET status = 'done', completed_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (_utc_now(), task_id),
            )
            return cursor.rowcount == 1

    def delete_task(self, task_id):
        task_id = self._validate_task_id(task_id)
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cursor.rowcount == 1

    @staticmethod
    def _validate_task_id(task_id):
        try:
            task_id = int(task_id)
        except (TypeError, ValueError) as error:
            raise ValueError("任务编号必须是数字") from error
        if task_id <= 0:
            raise ValueError("任务编号必须是正整数")
        return task_id

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from conversation_manager import DEFAULT_DATABASE

DISPLAY_FORMAT = "%Y-%m-%d %H:%M"


def _utc_now():
    return datetime.now(timezone.utc)


class ReminderManager:
    """管理本地一次性文字提醒。"""

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
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'done')),
                    created_at TEXT NOT NULL,
                    notified_at TEXT,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS reminders_due
                ON reminders(status, notified_at, due_at);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(reminders)").fetchall()
            }
            if "remote_notified_at" not in columns:
                connection.execute(
                    "ALTER TABLE reminders ADD COLUMN remote_notified_at TEXT"
                )
            if "remote_last_attempt_at" not in columns:
                connection.execute(
                    "ALTER TABLE reminders ADD COLUMN remote_last_attempt_at TEXT"
                )
            if "remote_attempts" not in columns:
                connection.execute(
                    "ALTER TABLE reminders ADD COLUMN remote_attempts INTEGER NOT NULL DEFAULT 0"
                )

    @staticmethod
    def parse_local_time(value):
        if not isinstance(value, str):
            raise ValueError("提醒时间必须是文本")
        try:
            local_time = datetime.strptime(value.strip(), DISPLAY_FORMAT)
        except ValueError as error:
            raise ValueError("时间格式必须是 YYYY-MM-DD HH:MM") from error

        local_zone = datetime.now().astimezone().tzinfo
        return local_time.replace(tzinfo=local_zone).astimezone(timezone.utc)

    def add_reminder(self, title, due_time):
        if not isinstance(title, str) or not title.strip():
            raise ValueError("提醒内容不能为空")
        due_at = self.parse_local_time(due_time)
        if due_at <= _utc_now():
            raise ValueError("提醒时间必须晚于当前时间")

        now = _utc_now().isoformat(timespec="seconds")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reminders (title, due_at, created_at)
                VALUES (?, ?, ?)
                """,
                (title.strip(), due_at.isoformat(timespec="seconds"), now),
            )
            return cursor.lastrowid

    def list_reminders(self, include_done=False):
        query = "SELECT * FROM reminders"
        parameters = ()
        if not include_done:
            query += " WHERE status = ?"
            parameters = ("pending",)
        query += " ORDER BY due_at ASC, id ASC"

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._present(dict(row)) for row in rows]

    def claim_due_reminders(self, now=None):
        now = now or _utc_now()
        now_text = now.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM reminders
                WHERE status = 'pending'
                  AND notified_at IS NULL
                  AND due_at <= ?
                ORDER BY due_at ASC, id ASC
                """,
                (now_text,),
            ).fetchall()
            if rows:
                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"UPDATE reminders SET notified_at = ? WHERE id IN ({placeholders})",
                    (now_text, *ids),
                )
        return [self._present(dict(row)) for row in rows]

    def complete_reminder(self, reminder_id):
        reminder_id = self._validate_id(reminder_id)
        now = _utc_now().isoformat(timespec="seconds")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE reminders
                SET status = 'done', completed_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, reminder_id),
            )
            return cursor.rowcount == 1

    def claim_remote_due(self, now=None, retry_after_seconds=300):
        """取得需要远程发送的到期提醒，并记录尝试以限制重试频率。"""
        now = now or _utc_now()
        now_text = now.astimezone(timezone.utc).isoformat(timespec="seconds")
        retry_before = (now - timedelta(seconds=retry_after_seconds)).astimezone(
            timezone.utc
        ).isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM reminders
                WHERE status = 'pending'
                  AND due_at <= ?
                  AND remote_notified_at IS NULL
                  AND (remote_last_attempt_at IS NULL OR remote_last_attempt_at <= ?)
                ORDER BY due_at ASC, id ASC
                """,
                (now_text, retry_before),
            ).fetchall()
            if rows:
                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"""
                    UPDATE reminders
                    SET remote_last_attempt_at = ?, remote_attempts = remote_attempts + 1
                    WHERE id IN ({placeholders})
                    """,
                    (now_text, *ids),
                )
        return [self._present(dict(row)) for row in rows]

    def mark_remote_notified(self, reminder_id, now=None):
        reminder_id = self._validate_id(reminder_id)
        now = now or _utc_now()
        now_text = now.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE reminders SET remote_notified_at = ?
                WHERE id = ? AND remote_notified_at IS NULL
                """,
                (now_text, reminder_id),
            )
            return cursor.rowcount == 1

    def delete_reminder(self, reminder_id):
        reminder_id = self._validate_id(reminder_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM reminders WHERE id = ?", (reminder_id,)
            )
            return cursor.rowcount == 1

    @staticmethod
    def _validate_id(value):
        try:
            value = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("提醒编号必须是数字") from error
        if value <= 0:
            raise ValueError("提醒编号必须是正整数")
        return value

    @staticmethod
    def _present(row):
        due_at = datetime.fromisoformat(row["due_at"]).astimezone()
        row["due_local"] = due_at.strftime(DISPLAY_FORMAT)
        return row

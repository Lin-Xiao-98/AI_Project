import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE = PROJECT_DIR / "data" / "assistant.db"
VALID_ROLES = {"user", "assistant"}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConversationManager:
    """使用本地 SQLite 保存会话；不向任何外部服务同步。"""

    def __init__(self, database_path=DEFAULT_DATABASE):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS messages_session_id
                ON messages(session_id, id);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS channel_messages (
                    channel TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('processing', 'completed')),
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    PRIMARY KEY (channel, message_id)
                );
                """
            )

    def _get_active_session_id(self, connection):
        row = connection.execute(
            "SELECT value FROM settings WHERE key = 'active_session_id'"
        ).fetchone()
        return row["value"] if row else None

    def get_or_create_active_session(self):
        with self._connect() as connection:
            session_id = self._get_active_session_id(connection)
            if session_id:
                exists = connection.execute(
                    "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if exists:
                    return session_id

        return self.start_new_session()

    def start_new_session(self):
        session_id = uuid.uuid4().hex
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions (id, created_at, updated_at) VALUES (?, ?, ?)",
                (session_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO settings (key, value)
                VALUES ('active_session_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (session_id,),
            )
        return session_id

    def get_or_create_scoped_session(self, channel, subject):
        """为外部通道中的单个使用者保存独立会话，不改变终端当前会话。"""
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("通道名称不能为空")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("会话主体不能为空")
        digest = hashlib.sha256(
            f"{channel.strip()}:{subject.strip()}".encode("utf-8")
        ).hexdigest()
        setting_key = f"channel_session:{digest}"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (setting_key,)
            ).fetchone()
            if row:
                exists = connection.execute(
                    "SELECT 1 FROM sessions WHERE id = ?", (row["value"],)
                ).fetchone()
                if exists:
                    return row["value"]
            session_id = uuid.uuid4().hex
            now = _utc_now()
            connection.execute(
                "INSERT INTO sessions (id, created_at, updated_at) VALUES (?, ?, ?)",
                (session_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (setting_key, session_id),
            )
        return session_id

    def start_new_scoped_session(self, channel, subject):
        """为指定外部聊天开始新上下文，同时保留旧会话记录。"""
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("通道名称不能为空")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("会话主体不能为空")
        digest = hashlib.sha256(
            f"{channel.strip()}:{subject.strip()}".encode("utf-8")
        ).hexdigest()
        setting_key = f"channel_session:{digest}"
        session_id = uuid.uuid4().hex
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions (id, created_at, updated_at) VALUES (?, ?, ?)",
                (session_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (setting_key, session_id),
            )
        return session_id

    def claim_channel_message(self, channel, message_id, lease_seconds=600):
        if not channel or not message_id:
            raise ValueError("通道和消息编号不能为空")
        now = datetime.now(timezone.utc)
        now_text = now.isoformat(timespec="seconds")
        stale_before = (now - timedelta(seconds=lease_seconds)).isoformat(
            timespec="seconds"
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, created_at FROM channel_messages
                WHERE channel = ? AND message_id = ?
                """,
                (str(channel), str(message_id)),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO channel_messages
                        (channel, message_id, status, created_at)
                    VALUES (?, ?, 'processing', ?)
                    """,
                    (str(channel), str(message_id), now_text),
                )
                return True
            if row["status"] == "processing" and row["created_at"] <= stale_before:
                connection.execute(
                    """
                    UPDATE channel_messages SET created_at = ?
                    WHERE channel = ? AND message_id = ? AND status = 'processing'
                    """,
                    (now_text, str(channel), str(message_id)),
                )
                return True
            return False

    def complete_channel_message(self, channel, message_id):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE channel_messages
                SET status = 'completed', completed_at = ?
                WHERE channel = ? AND message_id = ?
                """,
                (_utc_now(), str(channel), str(message_id)),
            )

    def release_channel_message(self, channel, message_id):
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM channel_messages
                WHERE channel = ? AND message_id = ? AND status = 'processing'
                """,
                (str(channel), str(message_id)),
            )

    def add_message(self, session_id, role, content):
        if role not in VALID_ROLES:
            raise ValueError(f"不支持的消息角色：{role}")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("消息内容不能为空")

        now = _utc_now()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not exists:
                raise ValueError("会话不存在")
            connection.execute(
                """
                INSERT INTO messages (session_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content.strip(), now),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )

    def load_messages(self, session_id, limit=40):
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("消息数量限制必须是正整数")

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM (
                    SELECT id, role, content
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                (session_id, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def count_messages(self, session_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row["total"]

    def recent_sessions(self, limit=5):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    sessions.id,
                    sessions.created_at,
                    sessions.updated_at,
                    COUNT(messages.id) AS message_count
                FROM sessions
                LEFT JOIN messages ON messages.session_id = sessions.id
                GROUP BY sessions.id
                ORDER BY sessions.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_setting(self, key, default=None):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        if not isinstance(key, str) or not key.strip():
            raise ValueError("设置名称不能为空")
        if not isinstance(value, str):
            raise ValueError("设置值必须是文本")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key.strip(), value),
            )

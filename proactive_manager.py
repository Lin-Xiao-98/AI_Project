"""低频、可暂停且遵守安静时段的主动消息调度。"""

from __future__ import annotations

import os
import random
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

from conversation_manager import DEFAULT_DATABASE
from web_search_manager import search_web


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


class ProactiveManager:
    def __init__(self, database=DEFAULT_DATABASE):
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.quiet_start = int(os.getenv("PROACTIVE_QUIET_START", "22"))
        self.quiet_end = int(os.getenv("PROACTIVE_QUIET_END", "9"))
        self.daily_limit = max(int(os.getenv("PROACTIVE_DAILY_LIMIT", "1")), 1)
        self.default_enabled = _bool_env("PROACTIVE_MESSAGES_ENABLED", True)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS proactive_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _get(self, key: str, default: str = "") -> str:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM proactive_state WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default

    def _set(self, key: str, value: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO proactive_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )
            connection.commit()

    def enabled(self) -> bool:
        return self._get("enabled", str(self.default_enabled)).lower() == "true"

    def set_enabled(self, enabled: bool) -> None:
        self._set("enabled", str(bool(enabled)))
        if enabled and not self._get("next_due"):
            self._schedule_next(datetime.now().astimezone(), 6, 12)

    def _in_quiet_hours(self, now: datetime) -> bool:
        hour = now.hour
        if self.quiet_start > self.quiet_end:
            return hour >= self.quiet_start or hour < self.quiet_end
        return self.quiet_start <= hour < self.quiet_end

    def _active_time(self, candidate: datetime) -> datetime:
        while self._in_quiet_hours(candidate):
            candidate += timedelta(hours=1)
        return candidate

    def _schedule_next(self, now: datetime, minimum: int = 18, maximum: int = 34):
        candidate = self._active_time(now + timedelta(hours=random.randint(minimum, maximum)))
        self._set("next_due", candidate.isoformat(timespec="seconds"))

    def is_due(self, now: datetime | None = None) -> bool:
        now = now or datetime.now().astimezone()
        if not self.enabled() or self._in_quiet_hours(now):
            return False
        sent_date = self._get("sent_date")
        sent_today = int(self._get("sent_today", "0")) if sent_date == now.date().isoformat() else 0
        if sent_today >= self.daily_limit:
            return False
        raw_due = self._get("next_due")
        if not raw_due:
            self._schedule_next(now, 6, 12)
            return False
        try:
            return now >= datetime.fromisoformat(raw_due)
        except ValueError:
            self._schedule_next(now, 6, 12)
            return False

    def compose(self, client) -> str:
        sent_total = int(self._get("sent_total", "0"))
        if sent_total % 3 == 2:
            return "给你分享一件轻松的小趣事：\n" + search_web(
                client,
                "找一件最近24小时内真实、轻松、正面的科技或生活趣闻。"
                "用两三句话讲清楚，并附可靠来源链接。不要涉及灾难、冲突或令人焦虑的内容。",
                max_completion_tokens=450,
            )
        messages = (
            "路过来看看你。今天别忘了喝点水，也给眼睛休息几分钟。有什么想做的，随时叫我。",
            "忙到现在辛苦啦。给自己留一点喘气的时间吧；如果有琐事想整理，可以直接交给我。",
            "今天过得怎么样？不用特意回复我。只是提醒你：累了就休息一下，我一直在。",
        )
        return messages[sent_total % len(messages)]

    def record_sent(self, now: datetime | None = None) -> None:
        now = now or datetime.now().astimezone()
        today = now.date().isoformat()
        count = int(self._get("sent_today", "0")) if self._get("sent_date") == today else 0
        self._set("sent_date", today)
        self._set("sent_today", str(count + 1))
        self._set("sent_total", str(int(self._get("sent_total", "0")) + 1))
        self._set("last_sent", now.isoformat(timespec="seconds"))
        self._schedule_next(now)

    def record_failure(self, now: datetime | None = None) -> None:
        now = now or datetime.now().astimezone()
        self._set("next_due", self._active_time(now + timedelta(hours=2)).isoformat(timespec="seconds"))

    def status(self) -> dict:
        return {
            "enabled": self.enabled(),
            "next_due": self._get("next_due") or "尚未安排",
            "last_sent": self._get("last_sent") or "尚未发送",
            "quiet_hours": f"{self.quiet_start:02d}:00-{self.quiet_end:02d}:00",
            "daily_limit": self.daily_limit,
        }

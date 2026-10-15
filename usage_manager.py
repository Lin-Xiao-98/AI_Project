"""OpenAI API 本地用量审计和硬预算保护。"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from conversation_manager import DEFAULT_DATABASE


def _positive_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = int(value)
    except ValueError as error:
        raise RuntimeError(f"{name} 必须是正整数。") from error
    if parsed <= 0:
        raise RuntimeError(f"{name} 必须是正整数。")
    return parsed


class UsageManager:
    def __init__(self, database_path=DEFAULT_DATABASE):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
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
                CREATE TABLE IF NOT EXISTS api_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    model TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS api_usage_created_at
                ON api_usage(created_at);
                """
            )

    @staticmethod
    def limits():
        return {
            "daily_requests": _positive_int("DAILY_API_REQUEST_LIMIT", 120),
            "daily_tokens": _positive_int("DAILY_API_TOKEN_LIMIT", 200_000),
            "monthly_requests": _positive_int("MONTHLY_API_REQUEST_LIMIT", 3_000),
            "monthly_tokens": _positive_int("MONTHLY_API_TOKEN_LIMIT", 2_000_000),
        }

    def summary(self):
        now = datetime.now().astimezone()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        month_start = day_start.replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

        def utc_text(value):
            return value.astimezone(timezone.utc).isoformat(timespec="seconds")

        with self._connect() as connection:
            day = connection.execute(
                """
                SELECT COUNT(*) AS requests, COALESCE(SUM(total_tokens), 0) AS tokens
                FROM api_usage WHERE created_at >= ? AND created_at < ?
                """,
                (utc_text(day_start), utc_text(day_end)),
            ).fetchone()
            month = connection.execute(
                """
                SELECT COUNT(*) AS requests, COALESCE(SUM(total_tokens), 0) AS tokens
                FROM api_usage WHERE created_at >= ? AND created_at < ?
                """,
                (utc_text(month_start), utc_text(next_month)),
            ).fetchone()
        return {
            "day_requests": day["requests"],
            "day_tokens": day["tokens"],
            "month_requests": month["requests"],
            "month_tokens": month["tokens"],
            **self.limits(),
        }

    def ensure_available(self):
        if os.getenv("API_HARD_LIMIT_ENABLED", "true").strip().lower() != "true":
            return
        current = self.summary()
        checks = (
            ("今日请求次数", current["day_requests"], current["daily_requests"]),
            ("今日 token", current["day_tokens"], current["daily_tokens"]),
            ("本月请求次数", current["month_requests"], current["monthly_requests"]),
            ("本月 token", current["month_tokens"], current["monthly_tokens"]),
        )
        for label, used, limit in checks:
            if used >= limit:
                raise RuntimeError(
                    f"API 硬预算已停止调用：{label} {used}/{limit}。"
                    "如确需继续，请在本机调整 .env 中的额度上限。"
                )

    def record(
        self,
        model: str,
        operation: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
    ):
        input_tokens = max(int(input_tokens or 0), 0)
        output_tokens = max(int(output_tokens or 0), 0)
        cached_input_tokens = max(int(cached_input_tokens or 0), 0)
        total_tokens = input_tokens + output_tokens
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO api_usage
                    (created_at, model, operation, input_tokens,
                     cached_input_tokens, output_tokens, total_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    str(model or "unknown"),
                    str(operation or "unknown"),
                    input_tokens,
                    cached_input_tokens,
                    output_tokens,
                    total_tokens,
                ),
            )

    def record_response(self, response, model: str, operation: str):
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_tokens = getattr(usage, "prompt_tokens", None)
        if input_tokens is None:
            input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "completion_tokens", None)
        if output_tokens is None:
            output_tokens = getattr(usage, "output_tokens", 0)
        details = getattr(usage, "prompt_tokens_details", None)
        if details is None:
            details = getattr(usage, "input_tokens_details", None)
        cached_tokens = getattr(details, "cached_tokens", 0) if details else 0
        self.record(
            model,
            operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
        )


USAGE_MANAGER = UsageManager()

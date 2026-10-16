import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from usage_manager import UsageManager


class UsageManagerTests(unittest.TestCase):
    def test_records_tokens_and_enforces_hard_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = UsageManager(Path(folder) / "assistant.db")
            usage = SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=SimpleNamespace(cached_tokens=3),
            )
            manager.record_response(SimpleNamespace(usage=usage), "model", "chat")
            summary = manager.summary()
            self.assertEqual(summary["day_requests"], 1)
            self.assertEqual(summary["day_tokens"], 15)
            with patch.dict(
                "os.environ",
                {
                    "DAILY_API_REQUEST_LIMIT": "1",
                    "DAILY_API_TOKEN_LIMIT": "100",
                    "MONTHLY_API_REQUEST_LIMIT": "10",
                    "MONTHLY_API_TOKEN_LIMIT": "1000",
                },
            ):
                with self.assertRaisesRegex(RuntimeError, "硬预算"):
                    manager.ensure_available()

    def test_response_without_usage_is_not_counted(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = UsageManager(Path(folder) / "assistant.db")
            manager.record_response(SimpleNamespace(), "fake", "test")
            self.assertEqual(manager.summary()["day_requests"], 0)


if __name__ == "__main__":
    unittest.main()

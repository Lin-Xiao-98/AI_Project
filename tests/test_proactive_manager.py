import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from proactive_manager import ProactiveManager


class ProactiveManagerTests(unittest.TestCase):
    def test_respects_toggle_quiet_hours_and_daily_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "assistant.db"
            with patch.dict(
                "os.environ",
                {
                    "PROACTIVE_QUIET_START": "22",
                    "PROACTIVE_QUIET_END": "9",
                    "PROACTIVE_DAILY_LIMIT": "1",
                },
            ):
                manager = ProactiveManager(database)
            manager.set_enabled(True)
            manager._set("next_due", "2026-10-15T10:00:00+08:00")
            active = datetime.fromisoformat("2026-10-16T10:00:00+08:00")
            quiet = datetime.fromisoformat("2026-10-16T23:00:00+08:00")
            self.assertTrue(manager.is_due(active))
            self.assertFalse(manager.is_due(quiet))
            manager.record_sent(active)
            self.assertFalse(manager.is_due(active))
            manager.set_enabled(False)
            self.assertFalse(manager.enabled())


if __name__ == "__main__":
    unittest.main()

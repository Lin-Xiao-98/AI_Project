import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import reminder_manager
from reminder_manager import ReminderManager


class ReminderManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.manager = ReminderManager(
            Path(self.temp_directory.name) / "assistant.db"
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_reminder_lifecycle_and_claim(self):
        fixed_now = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
        future_local = (fixed_now + timedelta(hours=2)).astimezone().strftime(
            reminder_manager.DISPLAY_FORMAT
        )
        with patch.object(reminder_manager, "_utc_now", return_value=fixed_now):
            reminder_id = self.manager.add_reminder("验收项目", future_local)

        self.assertEqual(self.manager.list_reminders()[0]["title"], "验收项目")
        self.assertEqual(
            self.manager.claim_due_reminders(fixed_now + timedelta(hours=1)), []
        )
        due = self.manager.claim_due_reminders(fixed_now + timedelta(hours=3))
        self.assertEqual(due[0]["id"], reminder_id)
        self.assertEqual(
            self.manager.claim_due_reminders(fixed_now + timedelta(hours=4)), []
        )
        self.assertTrue(self.manager.complete_reminder(reminder_id))

    def test_past_and_invalid_times_are_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.add_reminder("测试", "错误时间")
        past = (datetime.now().astimezone() - timedelta(days=1)).strftime(
            reminder_manager.DISPLAY_FORMAT
        )
        with self.assertRaises(ValueError):
            self.manager.add_reminder("测试", past)

    def test_delete_reminder(self):
        future = (datetime.now().astimezone() + timedelta(days=1)).strftime(
            reminder_manager.DISPLAY_FORMAT
        )
        reminder_id = self.manager.add_reminder("待删除", future)
        self.assertTrue(self.manager.delete_reminder(reminder_id))
        self.assertEqual(self.manager.list_reminders(), [])

    def test_remote_notification_retries_then_marks_success(self):
        fixed_now = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
        future_local = (fixed_now + timedelta(minutes=1)).astimezone().strftime(
            reminder_manager.DISPLAY_FORMAT
        )
        with patch.object(reminder_manager, "_utc_now", return_value=fixed_now):
            reminder_id = self.manager.add_reminder("远程提醒", future_local)

        check_time = fixed_now + timedelta(minutes=2)
        first = self.manager.claim_remote_due(check_time)
        self.assertEqual([item["id"] for item in first], [reminder_id])
        self.assertEqual(self.manager.claim_remote_due(check_time), [])
        retry = self.manager.claim_remote_due(check_time + timedelta(minutes=6))
        self.assertEqual([item["id"] for item in retry], [reminder_id])
        self.assertTrue(
            self.manager.mark_remote_notified(
                reminder_id, check_time + timedelta(minutes=6)
            )
        )
        self.assertEqual(
            self.manager.claim_remote_due(check_time + timedelta(minutes=12)), []
        )


if __name__ == "__main__":
    unittest.main()

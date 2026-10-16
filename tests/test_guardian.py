import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import assistant_guardian
import guardian_control
from single_instance import SingleInstance


class GuardianTests(unittest.TestCase):
    def test_duplicate_start_does_not_overwrite_running_status(self):
        with (
            patch("assistant_guardian._logger") as logger,
            patch("assistant_guardian._write_status") as write_status,
        ):
            assistant_guardian._report_duplicate(RuntimeError("already running"))
        logger.return_value.info.assert_called_once()
        write_status.assert_not_called()

    def test_stale_status_is_reported_as_stopped(self):
        with tempfile.TemporaryDirectory() as temporary:
            status_file = Path(temporary) / "status.json"
            status_file.write_text(
                json.dumps({"state": "running", "guardian_pid": 123}),
                encoding="utf-8",
            )
            with (
                patch.object(guardian_control, "STATUS_FILE", status_file),
                patch.object(guardian_control, "_pid_running", return_value=False),
            ):
                status = guardian_control.read_status()
        self.assertEqual(status["state"], "stopped")

    def test_running_status_checks_child_process(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(guardian_control, "STATUS_FILE", Path(folder) / "status.json"),
            patch.object(
                guardian_control,
                "_pid_running",
                side_effect=lambda pid: pid == 100,
            ),
        ):
            guardian_control.STATUS_FILE.write_text(
                '{"state":"running","guardian_pid":100,"child_pid":200}',
                encoding="utf-8",
            )
            status = guardian_control.read_status()
            self.assertEqual(status["state"], "restarting")

    def test_inbox_cleanup_only_removes_expired_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            inbox = Path(temporary)
            expired = inbox / "expired.txt"
            current = inbox / "current.txt"
            expired.write_text("old", encoding="utf-8")
            current.write_text("new", encoding="utf-8")
            old_time = time.time() - 31 * 86400
            os.utime(expired, (old_time, old_time))
            with patch.object(assistant_guardian, "INBOX_DIR", inbox):
                removed = assistant_guardian._prune_inbox(30)
            self.assertEqual(removed, 1)
            self.assertFalse(expired.exists())
            self.assertTrue(current.exists())

    def test_single_instance_rejects_second_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = SingleInstance("test")
            second = SingleInstance("test")
            path = Path(temporary) / "test.lock"
            first.path = path
            second.path = path
            with first:
                with self.assertRaises(RuntimeError):
                    with second:
                        pass


if __name__ == "__main__":
    unittest.main()

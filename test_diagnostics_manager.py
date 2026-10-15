import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diagnostics_manager import create_diagnostic_report
from task_manager import TaskManager


class DiagnosticsManagerTests(unittest.TestCase):
    def test_report_contains_health_but_not_private_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "assistant.db"
            TaskManager(database).add_task("绝不能出现在诊断报告里的私密任务")
            with (
                patch("diagnostics_manager.read_status", return_value={"state": "running"}),
                patch("diagnostics_manager.get_secret", return_value="secret-value"),
            ):
                path = create_diagnostic_report(root / "reports", database, root)

            text = path.read_text(encoding="utf-8")
            report = json.loads(text)
            self.assertEqual(report["database"]["integrity"], "ok")
            self.assertEqual(report["database"]["counts"]["tasks"], 1)
            self.assertTrue(report["secrets_ready"]["openai"])
            self.assertNotIn("secret-value", text)
            self.assertNotIn("私密任务", text)


if __name__ == "__main__":
    unittest.main()

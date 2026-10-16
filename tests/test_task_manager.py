import tempfile
import unittest
from pathlib import Path

from task_manager import TaskManager


class TaskManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_directory.name) / "assistant.db"
        self.manager = TaskManager(self.database)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_task_lifecycle(self):
        task_id = self.manager.add_task("完成 AI 助手测试")
        self.assertEqual(self.manager.list_tasks()[0]["title"], "完成 AI 助手测试")

        self.assertTrue(self.manager.complete_task(task_id))
        self.assertEqual(self.manager.list_tasks(), [])
        self.assertEqual(self.manager.list_tasks(include_done=True)[0]["status"], "done")

        self.assertTrue(self.manager.delete_task(task_id))
        self.assertEqual(self.manager.list_tasks(include_done=True), [])

    def test_missing_task_returns_false(self):
        self.assertFalse(self.manager.complete_task(999))
        self.assertFalse(self.manager.delete_task(999))

    def test_invalid_task_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.add_task(" ")
        with self.assertRaises(ValueError):
            self.manager.complete_task("abc")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from action_manager import ActionManager
from natural_command_manager import handle_natural_command
from reminder_manager import ReminderManager
from task_manager import TaskManager


class NaturalCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        database = Path(self.temp_directory.name) / "assistant.db"
        self.tasks = TaskManager(database)
        self.reminders = ReminderManager(database)
        self.actions = ActionManager(database, Path(self.temp_directory.name) / "workspace")
        self.now = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_adds_and_lists_task_without_slash_command(self):
        reply = handle_natural_command(
            "帮我添加一个待办：整理剪辑素材", self.tasks, self.reminders, self.now
        )
        self.assertIn("整理剪辑素材", reply)
        self.assertIn(
            "整理剪辑素材",
            handle_natural_command("我有哪些待办", self.tasks, self.reminders, self.now),
        )

    def test_adds_relative_reminder(self):
        reply = handle_natural_command(
            "提醒我明天晚上8点备份项目", self.tasks, self.reminders, self.now
        )
        self.assertIn("2026-10-17 20:00", reply)
        self.assertEqual(self.reminders.list_reminders()[0]["title"], "备份项目")

    def test_ordinary_chat_does_not_write(self):
        self.assertIsNone(
            handle_natural_command(
                "你觉得提醒功能设计得怎么样", self.tasks, self.reminders, self.now
            )
        )
        self.assertEqual(self.tasks.list_tasks(), [])
        self.assertEqual(self.reminders.list_reminders(), [])

    def test_completes_and_deletes_task_by_natural_name(self):
        first = self.tasks.add_task("整理今天的素材")
        self.tasks.add_task("导出成片")
        reply = handle_natural_command(
            "完成待办整理今天的素材", self.tasks, self.reminders, self.now
        )
        self.assertIn("整理今天的素材", reply)
        self.assertEqual(
            next(item for item in self.tasks.list_tasks(True) if item["id"] == first)["status"],
            "done",
        )
        reply = handle_natural_command(
            "删除待办导出成片", self.tasks, self.reminders, self.now
        )
        self.assertIn("导出成片", reply)

    def test_cancels_reminder_by_natural_name(self):
        self.reminders.add_reminder("给项目做备份", "2026-10-20 20:00")
        reply = handle_natural_command(
            "取消提醒给项目做备份", self.tasks, self.reminders, self.now
        )
        self.assertIn("给项目做备份", reply)
        self.assertEqual(self.reminders.list_reminders(), [])

    def test_approves_hex_action_id_without_slash(self):
        action = self.actions.prepare_file_creation("note.txt", "内容")
        reply = handle_natural_command(
            f"批准操作{action['action_id']}",
            self.tasks,
            self.reminders,
            self.now,
            self.actions,
        )
        self.assertEqual(reply, "已批准并创建：note.txt")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from action_manager import ActionManager
from assistant_service import AssistantService
from conversation_manager import ConversationManager
from knowledge_manager import KnowledgeManager
from proactive_manager import ProactiveManager
from reminder_manager import ReminderManager
from task_manager import TaskManager


class AssistantServiceCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        database = root / "assistant.db"
        self.service = AssistantService.__new__(AssistantService)
        self.service.conversations = ConversationManager(database)
        self.service.tasks = TaskManager(database)
        self.service.actions = ActionManager(database, root / "workspace")
        self.service.reminders = ReminderManager(database)
        self.service.knowledge = KnowledgeManager(database)
        self.service.proactive = ProactiveManager(database)
        self.service.model_mode = "fast"

    def tearDown(self):
        self.temporary.cleanup()

    def test_help_lists_zero_api_shortcuts(self):
        reply = self.service._remote_command("/help", "weixin", "me")
        self.assertIn("/联网", reply)
        self.assertIn("/diagnostics", reply)
        self.assertIn("/new", reply)

    def test_task_commands_add_complete_and_delete(self):
        self.assertIn("#1", self.service._remote_command("/todo add 测试", "weixin", "me"))
        self.assertIn("#1 测试", self.service._remote_command("/todo list", "weixin", "me"))
        self.assertEqual(
            self.service._remote_command("/todo done 1", "weixin", "me"),
            "待办已完成。",
        )
        self.assertEqual(
            self.service._remote_command("/todo delete 1", "weixin", "me"),
            "待办已删除。",
        )

    def test_model_mode_command_is_persistent(self):
        reply = self.service._remote_command("/mode balanced", "weixin", "me")
        self.assertIn("balanced", reply)
        self.assertEqual(self.service.model_mode, "balanced")
        self.assertEqual(self.service.conversations.get_setting("chat_mode"), "balanced")

    def test_new_command_replaces_only_scoped_context(self):
        first = self.service.conversations.get_or_create_scoped_session("weixin", "me")
        self.assertIn("长期记忆", self.service._remote_command("/new", "weixin", "me"))
        second = self.service.conversations.get_or_create_scoped_session("weixin", "me")
        self.assertNotEqual(first, second)

    def test_local_knowledge_search_command(self):
        source = Path(self.temporary.name) / "guide.txt"
        source.write_text("苹果手机维修预约流程和注意事项", encoding="utf-8")
        self.service.knowledge.add_document(source, "手机")
        reply = self.service._remote_command(
            "/knowledge search 苹果手机", "weixin", "me"
        )
        self.assertIn("guide（手机）", reply)
        self.assertIn("维修预约", reply)


if __name__ == "__main__":
    unittest.main()

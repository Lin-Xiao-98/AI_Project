import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tool_manager
from action_manager import ActionManager
from knowledge_manager import KnowledgeManager
from reminder_manager import ReminderManager
from task_manager import TaskManager


class ToolManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.task_manager = TaskManager(root / "assistant.db")
        self.action_manager = ActionManager(
            root / "assistant.db", root / "workspace"
        )
        self.reminder_manager = ReminderManager(root / "assistant.db")
        self.knowledge_manager = KnowledgeManager(root / "assistant.db")
        self.audit_file = root / "tool_audit.jsonl"
        self.audit_patch = patch.object(tool_manager, "AUDIT_FILE", self.audit_file)
        self.audit_patch.start()

    def tearDown(self):
        self.audit_patch.stop()
        self.temp_directory.cleanup()

    def test_time_tool_and_audit(self):
        result = json.loads(
            tool_manager.execute_tool("get_current_time", {}, self.task_manager)
        )
        self.assertIn("local_time", result)
        self.assertTrue(self.audit_file.exists())

    def test_audit_redacts_private_text_and_rotates(self):
        with patch.object(tool_manager, "MAX_AUDIT_BYTES", 1):
            self.audit_file.write_text("old", encoding="utf-8")
            tool_manager.execute_tool(
                "add_task", {"title": "不能写进日志的任务"}, self.task_manager
            )
        text = self.audit_file.read_text(encoding="utf-8")
        self.assertNotIn("不能写进日志", text)
        self.assertIn("redacted", text)
        self.assertTrue(self.audit_file.with_name("tool_audit.jsonl.1").exists())

    def test_expected_tools_are_exposed_to_model(self):
        names = {
            item["function"]["name"]
            for item in tool_manager.MODEL_TOOL_DEFINITIONS
        }
        self.assertEqual(
            names,
            {
                "search_web",
                "get_current_time",
                "list_project_files",
                "read_project_text_file",
                "list_tasks",
                "prepare_workspace_file",
                "search_knowledge",
            },
        )

    def test_search_knowledge_tool(self):
        source = Path(self.temp_directory.name) / "knowledge.txt"
        source.write_text("这里记录了工具检索测试内容。", encoding="utf-8")
        self.knowledge_manager.add_document(source, "测试")
        result = json.loads(
            tool_manager.execute_tool(
                "search_knowledge",
                {"query": "检索测试", "project": "测试"},
                self.task_manager,
                self.action_manager,
                self.reminder_manager,
                self.knowledge_manager,
            )
        )
        self.assertEqual(result["results"][0]["project"], "测试")

    def test_prepare_file_tool_requires_later_approval(self):
        result = json.loads(
            tool_manager.execute_tool(
                "prepare_workspace_file",
                {"path": "notes/test.md", "content": "测试内容"},
                self.task_manager,
                self.action_manager,
            )
        )
        self.assertEqual(result["status"], "pending")
        self.assertFalse(
            (self.action_manager.workspace_directory / "notes" / "test.md").exists()
        )

    def test_add_reminder_tool(self):
        from datetime import datetime, timedelta

        due = (datetime.now().astimezone() + timedelta(days=1)).strftime(
            "%Y-%m-%d %H:%M"
        )
        result = json.loads(
            tool_manager.execute_tool(
                "add_reminder",
                {"title": "测试提醒", "due_time": due},
                self.task_manager,
                self.action_manager,
                self.reminder_manager,
            )
        )
        self.assertEqual(result["reminder_id"], 1)

    def test_task_tools(self):
        added = json.loads(
            tool_manager.execute_tool(
                "add_task", {"title": "测试工具任务"}, self.task_manager
            )
        )
        listed = json.loads(
            tool_manager.execute_tool(
                "list_tasks", {"include_done": False}, self.task_manager
            )
        )
        self.assertEqual(added["task_id"], 1)
        self.assertEqual(listed["tasks"][0]["title"], "测试工具任务")

    def test_project_file_tools(self):
        listed = json.loads(
            tool_manager.execute_tool(
                "list_project_files", {"directory": "persona"}, self.task_manager
            )
        )
        self.assertIn("persona/Mr_L_only.txt", listed["files"])

        read = json.loads(
            tool_manager.execute_tool(
                "read_project_text_file",
                {"path": "persona/Mr_L_only.txt"},
                self.task_manager,
            )
        )
        self.assertIn("Core Persona", read["content"])

    def test_sensitive_and_outside_paths_are_blocked(self):
        with self.assertRaises(ValueError):
            tool_manager.execute_tool(
                "read_project_text_file", {"path": ".env"}, self.task_manager
            )
        with self.assertRaises(ValueError):
            tool_manager.execute_tool(
                "read_project_text_file", {"path": "../outside.txt"}, self.task_manager
            )
        with self.assertRaises(ValueError):
            tool_manager.execute_tool(
                "read_project_text_file", {"path": "memory.json"}, self.task_manager
            )


if __name__ == "__main__":
    unittest.main()

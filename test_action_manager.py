import tempfile
import unittest
from pathlib import Path

from action_manager import ActionManager


class ActionManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.workspace = root / "workspace"
        self.manager = ActionManager(root / "assistant.db", self.workspace)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_file_requires_approval_before_creation(self):
        action = self.manager.prepare_file_creation("notes/hello.md", "你好")
        target = self.workspace / "notes" / "hello.md"
        self.assertFalse(target.exists())
        self.assertEqual(len(self.manager.list_pending()), 1)

        approved = self.manager.approve(action["action_id"])
        self.assertEqual(approved, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "你好")
        self.assertEqual(self.manager.list_pending(), [])

    def test_rejected_file_is_not_created(self):
        action = self.manager.prepare_file_creation("draft.txt", "草稿")
        self.assertTrue(self.manager.reject(action["action_id"]))
        self.assertFalse((self.workspace / "draft.txt").exists())

    def test_outside_hidden_and_overwrite_are_blocked(self):
        with self.assertRaises(ValueError):
            self.manager.prepare_file_creation("../outside.txt", "内容")
        with self.assertRaises(ValueError):
            self.manager.prepare_file_creation(".secret.txt", "内容")

        self.workspace.mkdir(parents=True)
        (self.workspace / "exists.txt").write_text("原内容", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manager.prepare_file_creation("exists.txt", "新内容")


if __name__ == "__main__":
    unittest.main()

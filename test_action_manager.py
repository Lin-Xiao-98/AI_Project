import tempfile
import unittest
from pathlib import Path

from action_manager import ActionManager


class ActionManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.workspace = self.root / "workspace"
        self.manager = ActionManager(
            self.root / "assistant.db", self.workspace, managed_roots=[self.root]
        )

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

    def test_move_file_requires_approval_and_never_overwrites(self):
        source = self.root / "source.txt"
        destination = self.root / "renamed.txt"
        source.write_text("保留内容", encoding="utf-8")
        action = self.manager.prepare_file_move(str(source), str(destination))
        self.assertTrue(source.exists())
        self.assertFalse(destination.exists())

        approved = self.manager.approve(action["action_id"])

        self.assertEqual(approved, destination.resolve())
        self.assertFalse(source.exists())
        self.assertEqual(destination.read_text(encoding="utf-8"), "保留内容")

    def test_move_stops_if_source_changes_after_preview(self):
        source = self.root / "source.txt"
        destination = self.root / "destination.txt"
        source.write_text("第一版", encoding="utf-8")
        action = self.manager.prepare_file_move(str(source), str(destination))
        source.write_text("审批前被修改了", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "发生变化"):
            self.manager.approve(action["action_id"])
        self.assertFalse(destination.exists())

    def test_move_rejects_outside_managed_roots(self):
        source = self.root / "source.txt"
        source.write_text("内容", encoding="utf-8")
        outside = self.root.parent / "outside.txt"
        with self.assertRaisesRegex(ValueError, "授权"):
            self.manager.prepare_file_move(str(source), str(outside))


if __name__ == "__main__":
    unittest.main()

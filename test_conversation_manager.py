import tempfile
import unittest
from pathlib import Path

from conversation_manager import ConversationManager


class ConversationManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_directory.name) / "assistant.db"
        self.manager = ConversationManager(self.database)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_active_session_is_reused(self):
        first = self.manager.get_or_create_active_session()
        second = self.manager.get_or_create_active_session()
        self.assertEqual(first, second)

    def test_new_session_becomes_active(self):
        first = self.manager.get_or_create_active_session()
        second = self.manager.start_new_session()
        self.assertNotEqual(first, second)
        self.assertEqual(second, self.manager.get_or_create_active_session())

    def test_messages_are_saved_in_order(self):
        session_id = self.manager.get_or_create_active_session()
        self.manager.add_message(session_id, "user", "你好")
        self.manager.add_message(session_id, "assistant", "你好呀")

        self.assertEqual(
            self.manager.load_messages(session_id),
            [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好呀"},
            ],
        )
        self.assertEqual(self.manager.count_messages(session_id), 2)

    def test_load_messages_applies_limit_to_latest_messages(self):
        session_id = self.manager.get_or_create_active_session()
        for index in range(6):
            role = "user" if index % 2 == 0 else "assistant"
            self.manager.add_message(session_id, role, f"消息 {index}")

        messages = self.manager.load_messages(session_id, limit=2)
        self.assertEqual([item["content"] for item in messages], ["消息 4", "消息 5"])

    def test_invalid_messages_are_rejected(self):
        session_id = self.manager.get_or_create_active_session()
        with self.assertRaises(ValueError):
            self.manager.add_message(session_id, "system", "错误角色")
        with self.assertRaises(ValueError):
            self.manager.add_message(session_id, "user", "")

    def test_settings_are_persistent(self):
        self.assertEqual(self.manager.get_setting("chat_mode", "fast"), "fast")
        self.manager.set_setting("chat_mode", "balanced")
        self.assertEqual(self.manager.get_setting("chat_mode"), "balanced")

    def test_scoped_sessions_are_stable_and_separate(self):
        first = self.manager.get_or_create_scoped_session("wecom", "user-a")
        repeated = self.manager.get_or_create_scoped_session("wecom", "user-a")
        second = self.manager.get_or_create_scoped_session("wecom", "user-b")
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, second)

    def test_channel_message_dedup_can_release_failed_processing(self):
        self.assertTrue(self.manager.claim_channel_message("wecom", "msg-1"))
        self.assertFalse(self.manager.claim_channel_message("wecom", "msg-1"))
        self.manager.release_channel_message("wecom", "msg-1")
        self.assertTrue(self.manager.claim_channel_message("wecom", "msg-1"))
        self.manager.complete_channel_message("wecom", "msg-1")
        self.assertFalse(self.manager.claim_channel_message("wecom", "msg-1"))

    def test_stale_channel_message_claim_can_recover(self):
        self.assertTrue(self.manager.claim_channel_message("wecom", "stale"))
        with self.manager._connect() as connection:
            connection.execute(
                """
                UPDATE channel_messages SET created_at = '2000-01-01T00:00:00+00:00'
                WHERE channel = 'wecom' AND message_id = 'stale'
                """
            )
        self.assertTrue(self.manager.claim_channel_message("wecom", "stale"))


if __name__ == "__main__":
    unittest.main()

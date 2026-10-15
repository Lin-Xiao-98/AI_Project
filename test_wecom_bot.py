import os
import unittest
from unittest.mock import patch

import wecom_bot


class WeComBotTests(unittest.TestCase):
    def test_extract_text_and_voice(self):
        frame = {
            "body": {
                "msgid": "message-1",
                "chattype": "single",
                "from": {"userid": "owner"},
                "text": {"content": "你好"},
            }
        }
        self.assertEqual(
            wecom_bot.extract_message(frame, "text"),
            ("owner", "message-1", "single:owner:owner", "你好"),
        )
        frame["body"]["voice"] = {"content": "语音文字"}
        self.assertEqual(wecom_bot.extract_message(frame, "voice")[-1], "语音文字")

    def test_group_subject_remains_distinguishable(self):
        frame = {
            "body": {
                "msgid": "group-message",
                "chattype": "group",
                "chatid": "group-1",
                "from": {"userid": "owner"},
                "text": {"content": "不要公开资料"},
            }
        }
        self.assertEqual(
            wecom_bot.extract_message(frame, "text")[2],
            "group:group-1:owner",
        )

    def test_config_requires_enable_credentials_and_allowlist(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                wecom_bot.load_wecom_config()
        values = {
            "WECOM_ENABLED": "true",
            "WECOM_BOT_ID": "bot",
            "WECOM_BOT_SECRET": "secret",
            "WECOM_ALLOWED_USER_IDS": "owner",
        }
        with patch.dict(os.environ, values, clear=True):
            bot_id, secret, users = wecom_bot.load_wecom_config()
        self.assertEqual((bot_id, secret), ("bot", "secret"))
        self.assertEqual(users, {"owner"})

    def test_multiple_owners_are_rejected(self):
        values = {
            "WECOM_ENABLED": "true",
            "WECOM_BOT_ID": "bot",
            "WECOM_BOT_SECRET": "secret",
            "WECOM_ALLOWED_USER_IDS": "owner,second",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaises(RuntimeError):
                wecom_bot.load_wecom_config()

    def test_long_reply_is_utf8_safely_truncated(self):
        result = wecom_bot.limit_reply("你" * 5000)
        self.assertLessEqual(len(result.encode("utf-8")), 10000)
        self.assertIn("安全截断", result)


if __name__ == "__main__":
    unittest.main()

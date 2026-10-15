import tempfile
import unittest
from pathlib import Path

from weixin_api import WeixinApi, WeixinApiError, _safe_base_url
from weixin_bot import WeixinAccount, extract_text, load_account, save_account


class WeixinApiTests(unittest.TestCase):
    def test_only_official_https_hosts_are_accepted(self):
        self.assertEqual(_safe_base_url(None), "https://ilinkai.weixin.qq.com")
        self.assertEqual(
            _safe_base_url("https://foo.weixin.qq.com/"),
            "https://foo.weixin.qq.com",
        )
        with self.assertRaises(ValueError):
            _safe_base_url("http://ilinkai.weixin.qq.com")
        with self.assertRaises(ValueError):
            _safe_base_url("https://example.com")

    def test_send_text_builds_official_message_shape(self):
        api = WeixinApi(token="secret-for-test")
        captured = {}

        def fake_request(method, endpoint, payload=None, **kwargs):
            captured.update(
                method=method, endpoint=endpoint, payload=payload, kwargs=kwargs
            )
            return {"ret": 0}

        api._request_json = fake_request
        api.send_text("user-1", "你好", "ctx-1")
        self.assertEqual(captured["endpoint"], "ilink/bot/sendmessage")
        message = captured["payload"]["msg"]
        self.assertEqual(message["to_user_id"], "user-1")
        self.assertEqual(message["context_token"], "ctx-1")
        self.assertEqual(message["item_list"][0]["text_item"]["text"], "你好")

    def test_send_text_requires_context_token(self):
        with self.assertRaises(WeixinApiError):
            WeixinApi(token="secret-for-test").send_text("user-1", "你好", "")


class WeixinBotTests(unittest.TestCase):
    def test_extracts_text_and_voice_transcript(self):
        message = {
            "item_list": [
                {"type": 1, "text_item": {"text": "你好"}},
                {"type": 3, "voice_item": {"text": "帮我记住这件事"}},
            ]
        }
        self.assertEqual(extract_text(message), "你好\n帮我记住这件事")

    def test_account_state_round_trip_is_local(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "weixin_account.json"
            account = WeixinAccount("token", "bot", "owner")
            save_account(account, path)
            self.assertEqual(load_account(path), account)


if __name__ == "__main__":
    unittest.main()

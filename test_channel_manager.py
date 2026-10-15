import json
import unittest
from unittest.mock import patch

from channel_manager import WeComWebhookChannel

VALID_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key"


class FakeResponse:
    def __init__(self, result):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.result).encode("utf-8")


class WeComWebhookChannelTests(unittest.TestCase):
    def test_unconfigured_channel_is_inert(self):
        channel = WeComWebhookChannel("")
        self.assertFalse(channel.configured)
        with self.assertRaises(RuntimeError):
            channel.send_text("测试")

    def test_rejects_non_official_webhook(self):
        with self.assertRaises(ValueError):
            WeComWebhookChannel("https://example.com/webhook?key=x")

    def test_send_text_uses_official_endpoint(self):
        channel = WeComWebhookChannel(VALID_URL)
        with patch(
            "channel_manager.urlopen", return_value=FakeResponse({"errcode": 0})
        ) as mocked:
            channel.send_text("测试消息")
        request = mocked.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["text"]["content"], "测试消息")
        self.assertNotIn("test-key", body["text"]["content"])

    def test_send_failure_is_reported(self):
        channel = WeComWebhookChannel(VALID_URL)
        with patch(
            "channel_manager.urlopen",
            return_value=FakeResponse({"errcode": 93000, "errmsg": "invalid"}),
        ):
            with self.assertRaises(RuntimeError):
                channel.send_text("测试消息")


if __name__ == "__main__":
    unittest.main()

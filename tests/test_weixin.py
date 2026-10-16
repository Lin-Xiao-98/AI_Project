import base64
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weixin_api import WeixinApi, WeixinApiError, _safe_base_url
from weixin_bot import (
    SerialMessageWorker,
    WeixinAccount,
    attach_recent_video,
    extract_text,
    load_account,
    save_account,
    transcribe_voice_placeholders,
    voice_intent,
)
from weixin_media import MediaAttachment
from weixin_upload import UploadedMedia


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
        self.assertEqual(captured["payload"]["base_info"]["bot_agent"], "AIProject/1.3")

    def test_send_text_requires_context_token(self):
        with self.assertRaises(WeixinApiError):
            WeixinApi(token="secret-for-test").send_text("user-1", "你好", "")

    def test_send_file_builds_official_file_item(self):
        api = WeixinApi(token="secret-for-test")
        captured = {}

        def fake_request(method, endpoint, payload=None, **kwargs):
            captured.update(payload=payload)
            return {"ret": 0}

        api._request_json = fake_request
        uploaded = UploadedMedia("download-param", "ab" * 16, 123, 128)
        api.send_file("user-1", uploaded, "宝宝语音.mp3", "ctx-1")
        item = captured["payload"]["msg"]["item_list"][0]
        self.assertEqual(item["type"], 4)
        self.assertEqual(item["file_item"]["file_name"], "宝宝语音.mp3")
        self.assertEqual(item["file_item"]["len"], "123")
        self.assertEqual(
            item["file_item"]["media"]["aes_key"],
            base64.b64encode(("ab" * 16).encode("ascii")).decode("ascii"),
        )

    def test_send_rejects_business_error(self):
        api = WeixinApi(token="secret-for-test")
        api._request_json = lambda *_args, **_kwargs: {
            "ret": -2,
            "errmsg": "prepare failed",
        }
        with self.assertRaisesRegex(WeixinApiError, "ret=-2"):
            api.send_text("user-1", "你好", "ctx-1")

    def test_native_voice_payload_is_explicitly_experimental(self):
        api = WeixinApi(token="secret-for-test")
        captured = {}
        api._request_json = lambda _m, _e, payload=None, **_kwargs: (
            captured.update(payload=payload) or {"ret": 0}
        )
        uploaded = UploadedMedia("voice-param", "cd" * 16, 100, 112)
        api.send_voice_experimental(
            "user-1", uploaded, "ctx-1", playtime_ms=1200
        )
        item = captured["payload"]["msg"]["item_list"][0]
        self.assertEqual(item["type"], 3)
        self.assertEqual(item["voice_item"]["encode_type"], 7)
        self.assertNotIn("encrypt_type", item["voice_item"]["media"])


class WeixinBotTests(unittest.TestCase):
    def test_video_can_be_sent_before_followup_analysis_request(self):
        class Settings:
            def __init__(self):
                self.values = {}

            def set_setting(self, key, value):
                self.values[key] = value

            def get_setting(self, key, default=""):
                return self.values.get(key, default)

        with tempfile.TemporaryDirectory() as folder:
            inbox = Path(folder)
            video = inbox / "clip.mp4"
            video.write_bytes(b"video")
            service = SimpleNamespace(conversations=Settings())
            with patch("weixin_bot.INBOX_DIR", inbox):
                first = attach_recent_video(
                    service, "[视频]", [MediaAttachment("video", video)]
                )
                followup = attach_recent_video(service, "帮我拉片", [])
            self.assertEqual(first[0].path, video)
            self.assertEqual(followup, [MediaAttachment("video", video.resolve())])

    def test_missing_weixin_voice_text_is_transcribed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "voice.dat"
            converted = Path(folder) / "voice.wav"
            source.write_bytes(b"voice")
            converted.write_bytes(b"RIFF")
            service = SimpleNamespace(client=object())
            with (
                patch("weixin_bot.convert_voice_for_transcription", return_value=converted),
                patch("weixin_bot.transcribe_audio", return_value="帮我查看今天的待办"),
            ):
                content = transcribe_voice_placeholders(
                    service,
                    "[语音]",
                    [MediaAttachment("voice", source)],
                )
            self.assertEqual(content, "帮我查看今天的待办")
            self.assertFalse(converted.exists())

    def test_serial_worker_keeps_order_and_bounds_backlog(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        handled = []

        def handler(message):
            handled.append(message)
            if message == "first":
                started.set()
                release.wait(timeout=2)
            if message == "second":
                finished.set()

        worker = SerialMessageWorker(handler, max_pending=1)
        self.assertTrue(worker.submit("first"))
        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(worker.submit("second"))
        self.assertFalse(worker.submit("overflow"))
        release.set()
        self.assertTrue(finished.wait(timeout=2))
        self.assertEqual(handled, ["first", "second"])

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

    def test_voice_intent_understands_natural_language(self):
        self.assertEqual(voice_intent("以后都用语音回复我"), "on")
        self.assertEqual(voice_intent("以后用文字回复我"), "off")
        self.assertEqual(voice_intent("宝宝用语音回答这个问题"), "once")
        self.assertEqual(voice_intent("测试微信语音气泡"), "bubble_test")
        self.assertIsNone(voice_intent("为什么语音回复这么难实现"))


if __name__ == "__main__":
    unittest.main()

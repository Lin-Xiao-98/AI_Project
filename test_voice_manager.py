import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import voice_manager


class FakeTranscriptions:
    def __init__(self):
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(text="  测试转写文本  ")


class FakeStreamingResponse:
    def __init__(self):
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def stream_to_file(self, path):
        Path(path).write_bytes(b"fake mp3")


class VoiceManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_directory.name)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_validate_audio_file_rejects_missing_file(self):
        with self.assertRaisesRegex(ValueError, "找不到"):
            voice_manager.validate_audio_file(self.temp_path / "missing.wav")

    def test_validate_audio_file_rejects_unsupported_format(self):
        path = self.temp_path / "audio.txt"
        path.write_text("not audio", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "格式"):
            voice_manager.validate_audio_file(path)

    def test_transcribe_audio(self):
        path = self.temp_path / "sample.wav"
        path.write_bytes(b"RIFFfake")
        transcriptions = FakeTranscriptions()
        client = SimpleNamespace(
            audio=SimpleNamespace(transcriptions=transcriptions)
        )
        self.assertEqual(voice_manager.transcribe_audio(client, path), "测试转写文本")
        self.assertEqual(transcriptions.request["model"], "gpt-4o-mini-transcribe")

    def test_synthesize_speech_does_not_play_audio(self):
        streaming = FakeStreamingResponse()
        client = SimpleNamespace(
            audio=SimpleNamespace(
                speech=SimpleNamespace(with_streaming_response=streaming)
            )
        )
        with patch.object(voice_manager, "AUDIO_DIR", self.temp_path):
            path = voice_manager.synthesize_speech(client, "你好", provider="openai")
        self.assertEqual(path.read_bytes(), b"fake mp3")
        self.assertEqual(streaming.request["voice"], "shimmer")
        self.assertEqual(streaming.request["response_format"], "mp3")
        self.assertIn("十八至二十岁", streaming.request["instructions"])

    def test_synthesize_speech_accepts_voice_style_override(self):
        streaming = FakeStreamingResponse()
        client = SimpleNamespace(
            audio=SimpleNamespace(
                speech=SimpleNamespace(with_streaming_response=streaming)
            )
        )
        with patch.object(voice_manager, "AUDIO_DIR", self.temp_path):
            voice_manager.synthesize_speech(
                client,
                "试听",
                voice="coral",
                instructions="轻快地说中文。",
                provider="openai",
            )
        self.assertEqual(streaming.request["voice"], "coral")
        self.assertEqual(streaming.request["instructions"], "轻快地说中文。")

    def test_default_provider_uses_local_qwen_without_openai(self):
        def fake_run(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(b"local mp3")
            return SimpleNamespace(returncode=0, stdout=str(output), stderr="")

        fake_python = self.temp_path / "python.exe"
        fake_runner = self.temp_path / "runner.py"
        fake_python.write_bytes(b"exe")
        fake_runner.write_text("# runner", encoding="utf-8")
        with (
            patch.object(voice_manager, "AUDIO_DIR", self.temp_path),
            patch.object(voice_manager, "QWEN_TTS_PYTHON", fake_python),
            patch.object(voice_manager, "QWEN_TTS_RUNNER", fake_runner),
            patch.object(voice_manager.subprocess, "run", side_effect=fake_run) as run,
        ):
            path = voice_manager.synthesize_speech(None, "你好")
        self.assertEqual(path.read_bytes(), b"local mp3")
        self.assertIn("--instruction", run.call_args.args[0])

    def test_record_audio_rejects_invalid_duration(self):
        for duration in (0, 61, "abc"):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    voice_manager.record_audio(duration)


if __name__ == "__main__":
    unittest.main()

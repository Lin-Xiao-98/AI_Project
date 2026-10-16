import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import media_analysis_manager


class MediaAnalysisManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.video = self.root / "素材.mp4"
        self.video.write_bytes(b"video")

    def tearDown(self):
        self.temporary.cleanup()

    def test_timecode(self):
        self.assertEqual(media_analysis_manager._timecode(65.432), "00:01:05.432")

    def test_probe_video_returns_compact_metadata(self):
        payload = {
            "format": {"duration": "10.5", "format_long_name": "MP4"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "avg_frame_rate": "25/1"},
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
            ],
        }
        with (
            patch.object(media_analysis_manager, "_require_tools"),
            patch.object(
                media_analysis_manager,
                "_run",
                return_value=SimpleNamespace(stdout=json.dumps(payload)),
            ),
        ):
            result = media_analysis_manager.probe_video(self.video)
        self.assertEqual(result["duration_seconds"], 10.5)
        self.assertEqual(result["fps"], 25.0)
        self.assertEqual(result["audio_codec"], "aac")

    def test_rejects_non_video(self):
        text = self.root / "notes.txt"
        text.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            media_analysis_manager._video_path(text)


if __name__ == "__main__":
    unittest.main()

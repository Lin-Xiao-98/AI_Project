import tempfile
import unittest
from pathlib import Path

from secure_config import set_env_value


class SecureConfigTests(unittest.TestCase):
    def test_set_env_value_updates_one_setting_and_preserves_others(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text(
                "UNCHANGED=keep-me\nDAILY_API_TOKEN_LIMIT=200000\n",
                encoding="utf-8",
            )
            set_env_value("DAILY_API_TOKEN_LIMIT", "300000", path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("UNCHANGED=keep-me", text)
            self.assertIn("DAILY_API_TOKEN_LIMIT=300000", text)
            self.assertNotIn("DAILY_API_TOKEN_LIMIT=200000", text)

    def test_set_env_value_adds_missing_setting(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            set_env_value("TTS_PROVIDER", "qwen", path)
            self.assertEqual(path.read_text(encoding="utf-8"), "TTS_PROVIDER=qwen\n")

    def test_set_env_value_rejects_invalid_name_or_multiline_value(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            with self.assertRaises(ValueError):
                set_env_value("bad-name", "x", path)
            with self.assertRaises(ValueError):
                set_env_value("VALID_NAME", "a\nb", path)


if __name__ == "__main__":
    unittest.main()

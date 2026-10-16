import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import computer_manager


class ComputerManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_find_files_stays_inside_allowed_root(self):
        (self.root / "素材").mkdir()
        target = self.root / "素材" / "片段.mp4"
        target.write_bytes(b"video")
        with patch.object(computer_manager, "ALLOWED_SEARCH_ROOTS", (self.root,)):
            result = computer_manager.find_files(str(self.root), "片段", ".mp4")
        self.assertEqual(result["files"][0]["path"], str(target))

    def test_find_files_rejects_unapproved_root(self):
        allowed = self.root / "allowed"
        outside = self.root / "outside"
        allowed.mkdir()
        outside.mkdir()
        with patch.object(computer_manager, "ALLOWED_SEARCH_ROOTS", (allowed,)):
            with self.assertRaises(ValueError):
                computer_manager.find_files(str(outside), "test")

    def test_capture_screen_saves_locally(self):
        image = Image.new("RGB", (8, 6), "black")
        output = self.root / "screenshots"
        with (
            patch.object(computer_manager, "SCREENSHOT_DIR", output),
            patch.object(computer_manager.ImageGrab, "grab", return_value=image),
        ):
            result = computer_manager.capture_screen()
        self.assertTrue(Path(result["path"]).is_file())
        self.assertEqual((result["width"], result["height"]), (8, 6))
        self.assertIn("尚未上传", result["note"])

    def test_open_application_only_uses_fixed_candidate(self):
        executable = self.root / "safe.exe"
        executable.write_bytes(b"MZ")
        with (
            patch.object(
                computer_manager,
                "APPLICATION_CANDIDATES",
                {"notepad": (executable,)},
            ),
            patch.object(computer_manager.subprocess, "Popen") as popen,
        ):
            result = computer_manager.open_application("notepad")
        self.assertEqual(result["opened"], "notepad")
        self.assertEqual(popen.call_args.args[0], [str(executable.resolve())])

    def test_open_application_rejects_paths_and_unknown_apps(self):
        with self.assertRaises(ValueError):
            computer_manager.open_application("C:/Windows/System32/cmd.exe")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import health_check


class HealthCheckTests(unittest.TestCase):
    def test_qwen_check_reports_missing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (
                patch.object(health_check, "PROJECT_DIR", root),
                patch.object(health_check, "QWEN_PYTHON", root / "python.exe"),
                patch.object(health_check, "QWEN_MODEL", root / "model"),
                patch.object(health_check, "QWEN_WEIGHTS", root / "model" / "model.safetensors"),
            ):
                passed, detail = health_check.check_local_qwen()
        self.assertFalse(passed)
        self.assertIn("缺少", detail)

    def test_qwen_check_validates_runtime_and_cuda(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            python = root / "runtime" / "python.exe"
            model = root / "model"
            weights = model / "model.safetensors"
            python.parent.mkdir(parents=True)
            model.mkdir()
            python.write_bytes(b"exe")
            (model / "config.json").write_text("{}", encoding="utf-8")
            weights.write_bytes(b"weights")
            with (
                patch.object(health_check, "PROJECT_DIR", root),
                patch.object(health_check, "QWEN_PYTHON", python),
                patch.object(health_check, "QWEN_MODEL", model),
                patch.object(health_check, "QWEN_WEIGHTS", weights),
                patch.object(health_check, "MIN_QWEN_WEIGHTS_BYTES", 1),
                patch.object(
                    health_check.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout="cuda\n"),
                ),
            ):
                passed, detail = health_check.check_local_qwen()
        self.assertTrue(passed)
        self.assertIn("CUDA", detail)


if __name__ == "__main__":
    unittest.main()

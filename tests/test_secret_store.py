import os
import tempfile
import unittest
from pathlib import Path

from secret_store import delete_secret, get_secret, set_secret


@unittest.skipUnless(os.name == "nt", "需要 Windows DPAPI")
class SecretStoreTests(unittest.TestCase):
    def test_round_trip_is_encrypted_and_deletable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "secrets.json"
            set_secret("example", "plain-secret-value", path)
            self.assertNotIn("plain-secret-value", path.read_text(encoding="utf-8"))
            self.assertEqual(get_secret("example", path=path), "plain-secret-value")
            self.assertTrue(delete_secret("example", path))
            self.assertIsNone(get_secret("example", path=path))


if __name__ == "__main__":
    unittest.main()

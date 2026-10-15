import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from backup_manager import create_backup


class BackupManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_backup_contains_only_expected_data_files(self):
        memory_file = self.root / "memory.json"
        database_file = self.root / "assistant.db"
        env_file = self.root / ".env"
        memory_file.write_text('{"user": {}}', encoding="utf-8")
        with closing(sqlite3.connect(database_file)) as connection:
            connection.execute("CREATE TABLE sample (value TEXT)")
            connection.execute("INSERT INTO sample VALUES ('database')")
            connection.commit()
        env_file.write_text("OPENAI_API_KEY=secret", encoding="utf-8")

        backup = create_backup(
            memory_file, database_file, self.root / "backups"
        )

        with zipfile.ZipFile(backup) as archive:
            self.assertEqual(
                sorted(archive.namelist()), ["assistant.db", "memory.json"]
            )
            self.assertNotIn(".env", archive.namelist())
            extracted = self.root / "restored.db"
            extracted.write_bytes(archive.read("assistant.db"))
        with closing(sqlite3.connect(extracted)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0], "ok"
            )
            self.assertEqual(
                connection.execute("SELECT value FROM sample").fetchone()[0],
                "database",
            )

    def test_backup_requires_at_least_one_source(self):
        with self.assertRaises(ValueError):
            create_backup(
                self.root / "missing-memory.json",
                self.root / "missing.db",
                self.root / "backups",
            )


if __name__ == "__main__":
    unittest.main()

import os
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from backup_manager import create_backup, prune_backups, restore_backup


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

    def test_prune_keeps_recent_and_removes_old_excess(self):
        directory = self.root / "backups"
        directory.mkdir()
        now = datetime.now().timestamp()
        files = []
        for index in range(4):
            path = directory / f"ai_assistant_backup_{index}.zip"
            path.write_bytes(b"backup")
            modified = now - index * 20 * 86400
            os.utime(path, (modified, modified))
            files.append(path)
        removed = prune_backups(directory, keep=2, max_age_days=30)
        self.assertEqual(set(removed), {files[2], files[3]})
        self.assertTrue(files[0].exists())
        self.assertTrue(files[1].exists())

    def test_restore_validates_and_restores_data(self):
        memory = self.root / "memory.json"
        metadata = self.root / "memory_metadata.json"
        database = self.root / "assistant.db"
        backups = self.root / "backups"
        memory.write_text('{"user": {"preferences": ["原始记忆"]}}', encoding="utf-8")
        metadata.write_text('{"临时记忆": {"expires_at": "2099-01-01T00:00:00+00:00"}}', encoding="utf-8")
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE sample (value TEXT)")
            connection.execute("INSERT INTO sample VALUES ('original')")
            connection.commit()
        backup = create_backup(memory, database, backups)
        memory.write_text("{}", encoding="utf-8")
        metadata.write_text("{}", encoding="utf-8")
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("UPDATE sample SET value = 'changed'")
            connection.commit()
        safety = restore_backup(backup, memory, database, backups)
        self.assertTrue(safety.exists())
        self.assertIn("原始记忆", memory.read_text(encoding="utf-8"))
        self.assertIn("临时记忆", metadata.read_text(encoding="utf-8"))
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM sample").fetchone()[0], "original")


if __name__ == "__main__":
    unittest.main()

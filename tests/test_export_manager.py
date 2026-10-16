import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from export_manager import export_personal_data
from task_manager import TaskManager


class ExportManagerTests(unittest.TestCase):
    def test_export_contains_personal_data_but_no_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "assistant.db"
            TaskManager(database).add_task("导出测试任务")
            memory = root / "memory.json"
            memory.write_text('{"user":{"preferences":["咖啡"]}}', encoding="utf-8")
            path = export_personal_data(root / "exports", database, memory)

            with zipfile.ZipFile(path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"personal_data.json", "memory.json", "README.txt"},
                )
                data = json.loads(archive.read("personal_data.json"))
                self.assertEqual(data["database"]["tasks"][0]["title"], "导出测试任务")
                names = " ".join(archive.namelist()).lower()
                self.assertNotIn("secret", names)
                self.assertNotIn(".env", names)


if __name__ == "__main__":
    unittest.main()

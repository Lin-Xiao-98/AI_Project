import tempfile
import unittest
from pathlib import Path

from knowledge_manager import KnowledgeManager


class KnowledgeManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.manager = KnowledgeManager(self.root / "assistant.db")

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_add_list_search_and_deduplicate(self):
        source = self.root / "notes.md"
        source.write_text("项目目标是搭建可靠的个人 AI 助手。", encoding="utf-8")
        first = self.manager.add_document(source, "AI助手")
        second = self.manager.add_document(source, "AI助手")
        self.assertTrue(first["added"])
        self.assertFalse(second["added"])
        self.assertEqual(len(self.manager.list_documents()), 1)
        results = self.manager.search("可靠", "AI助手")
        self.assertEqual(results[0]["title"], "notes")

    def test_rejects_hidden_unsupported_and_empty_files(self):
        hidden = self.root / ".env"
        hidden.write_text("SECRET=x", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manager.add_document(hidden)
        unsupported = self.root / "notes.json"
        unsupported.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manager.add_document(unsupported)
        empty = self.root / "empty.txt"
        empty.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manager.add_document(empty)

    def test_project_filter_separates_context(self):
        one = self.root / "one.txt"
        two = self.root / "two.txt"
        one.write_text("共同关键词，甲项目资料", encoding="utf-8")
        two.write_text("共同关键词，乙项目资料", encoding="utf-8")
        self.manager.add_document(one, "甲")
        self.manager.add_document(two, "乙")
        results = self.manager.search("共同关键词", project="乙")
        self.assertEqual([item["project"] for item in results], ["乙"])

    def test_same_content_can_exist_in_two_projects_and_be_deleted(self):
        source = self.root / "shared.txt"
        source.write_text("相同资料内容", encoding="utf-8")
        first = self.manager.add_document(source, "甲")
        second = self.manager.add_document(source, "乙")
        self.assertNotEqual(first["document_id"], second["document_id"])
        self.assertTrue(self.manager.delete_document(first["document_id"]))
        self.assertEqual(self.manager.search("相同资料内容", "甲"), [])
        self.assertEqual(len(self.manager.search("相同资料内容", "乙")), 1)

    def test_percent_and_underscore_are_literal_search_terms(self):
        source = self.root / "symbols.txt"
        source.write_text("普通内容，不包含通配符", encoding="utf-8")
        self.manager.add_document(source)
        self.assertEqual(self.manager.search("%"), [])
        self.assertEqual(self.manager.search("_"), [])


if __name__ == "__main__":
    unittest.main()

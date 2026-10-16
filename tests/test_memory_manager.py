import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import memory_manager


class MemoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.memory_file = Path(self.temp_directory.name) / "memory.json"
        self.memory_file.write_text(
            json.dumps(memory_manager.EMPTY_MEMORY, ensure_ascii=False),
            encoding="utf-8",
        )
        self.memory_file_patch = patch.object(
            memory_manager, "MEMORY_FILE", self.memory_file
        )
        self.memory_file_patch.start()

    def tearDown(self):
        self.memory_file_patch.stop()
        self.temp_directory.cleanup()

    def test_save_and_exact_deduplication(self):
        self.assertTrue(
            memory_manager.save_memory("小林喜欢机械键盘。", "user", "preferences")
        )
        self.assertFalse(
            memory_manager.save_memory(" 小林喜欢机械键盘 ", "user", "preferences")
        )

        data = memory_manager.load_memory()
        self.assertEqual(data["user"]["preferences"], ["小林喜欢机械键盘。"])

    def test_deduplication_applies_across_categories(self):
        self.assertTrue(
            memory_manager.save_memory("小林喜欢安静。", "user", "preferences")
        )
        self.assertFalse(
            memory_manager.save_memory("小林喜欢安静", "projects", "测试项目")
        )

    def test_sensitive_values_are_rejected_at_storage_boundary(self):
        sensitive_values = (
            "API_KEY: sk-abcdefghijklmnop1234",
            "密码：super-secret-password",
            "身份证号是11010519491231002X",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdef123456",
            "Authorization: Bearer abcdefghijklmnop",
            "token: ghp_abcdefghijklmnopqrstuvwxyz123456",
            "我的密码是 abcdefgh",
            "API key is abcdefghijklmnop",
            "验证码是 123456",
            "token is abcdefghijklmnop",
        )
        for value in sensitive_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    memory_manager.save_memory(value, "temporary", "")

    def test_update_can_move_memory_to_another_category(self):
        memory_manager.save_memory("小林喜欢咖啡。", "user", "preferences")

        updated = memory_manager.update_memory(
            "小林喜欢咖啡。",
            "小林现在喜欢喝茶。",
            "user",
            "habits",
        )

        self.assertTrue(updated)
        data = memory_manager.load_memory()
        self.assertEqual(data["user"]["preferences"], [])
        self.assertEqual(data["user"]["habits"], ["小林现在喜欢喝茶。"])

    def test_update_to_existing_memory_removes_old_without_duplicate(self):
        memory_manager.save_memory("旧内容", "projects", "旧项目")
        memory_manager.save_memory("新内容", "user", "preferences")
        self.assertTrue(
            memory_manager.update_memory(
                "旧内容", "新内容", "user", "preferences"
            )
        )
        self.assertEqual(memory_manager.get_memory_count(), 1)
        self.assertNotIn("旧项目", memory_manager.load_memory()["projects"])

    def test_move_last_project_memory_removes_empty_project(self):
        memory_manager.save_memory("项目旧内容", "projects", "旧项目")
        self.assertTrue(
            memory_manager.update_memory(
                "项目旧内容", "用户新内容", "user", "preferences"
            )
        )
        self.assertEqual(memory_manager.load_memory()["projects"], {})

    def test_duplicate_update_does_not_create_empty_target_project(self):
        memory_manager.save_memory("待移除", "user", "habits")
        memory_manager.save_memory("已存在", "user", "preferences")
        self.assertTrue(
            memory_manager.update_memory(
                "待移除", "已存在", "projects", "不应创建"
            )
        )
        self.assertNotIn("不应创建", memory_manager.load_memory()["projects"])

    def test_delete_removes_empty_project(self):
        memory_manager.save_memory("项目使用 Python。", "projects", "AI_Project")

        self.assertTrue(memory_manager.delete_memory("项目使用 Python。"))
        self.assertEqual(memory_manager.load_memory()["projects"], {})

    def test_missing_target_does_not_change_file(self):
        before = self.memory_file.read_text(encoding="utf-8")
        self.assertFalse(memory_manager.delete_memory("不存在的记忆"))
        self.assertFalse(
            memory_manager.update_memory(
                "不存在的记忆", "新内容", "user", "preferences"
            )
        )
        self.assertEqual(self.memory_file.read_text(encoding="utf-8"), before)

    def test_v01_format_is_still_readable(self):
        self.memory_file.write_text(
            json.dumps({"memories": ["旧版记忆"]}, ensure_ascii=False),
            encoding="utf-8",
        )

        data = memory_manager.load_memory()
        self.assertEqual(data["user"]["preferences"], ["旧版记忆"])

    def test_legacy_path_is_migrated_to_private_data_path(self):
        legacy_file = Path(self.temp_directory.name) / "legacy_memory.json"
        private_file = Path(self.temp_directory.name) / "data" / "memory.json"
        legacy_file.write_text(
            json.dumps({"memories": ["需要保留的旧记忆"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        with patch.object(memory_manager, "MEMORY_FILE", private_file), patch.object(
            memory_manager, "LEGACY_MEMORY_FILE", legacy_file
        ):
            migrated = memory_manager.load_memory()
        self.assertTrue(private_file.exists())
        self.assertEqual(
            migrated["user"]["preferences"], ["需要保留的旧记忆"]
        )

    def test_invalid_location_is_rejected(self):
        with self.assertRaises(ValueError):
            memory_manager.save_memory("测试", "user", "unknown")
        with self.assertRaises(ValueError):
            memory_manager.save_memory("测试", "projects", "")

    def test_memory_count_includes_every_category(self):
        memory_manager.save_memory("偏好", "user", "preferences")
        memory_manager.save_memory("项目", "projects", "AI_Project")
        memory_manager.save_memory("临时", "temporary", "")
        self.assertEqual(memory_manager.get_memory_count(), 3)

    def test_expired_temporary_memory_is_pruned(self):
        memory_manager.save_memory("临时活动安排", "temporary")
        metadata_file = self.memory_file.with_name("memory_metadata.json")
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        key = memory_manager._normalise_text("临时活动安排")
        metadata[key]["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        metadata_file.write_text(json.dumps(metadata), encoding="utf-8")
        self.assertNotIn("临时活动安排", memory_manager.get_memory_text())


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main


class MainSafetyTests(unittest.TestCase):
    def test_ordinary_chat_cannot_use_write_tools(self):
        allowed = main.allowed_model_tools("你好，聊聊天吧")
        self.assertTrue(main.WRITE_TOOL_NAMES.isdisjoint(allowed))

    def test_natural_language_task_request_still_cannot_write(self):
        allowed = main.allowed_model_tools("请添加一个待办任务：整理资料")
        self.assertIn("list_tasks", allowed)
        self.assertTrue(main.WRITE_TOOL_NAMES.isdisjoint(allowed))

    def test_negative_task_sentence_cannot_write(self):
        allowed = main.allowed_model_tools("不要添加任务，请读取 README")
        self.assertTrue(main.WRITE_TOOL_NAMES.isdisjoint(allowed))

    def test_read_request_does_not_enable_write_tools(self):
        allowed = main.allowed_model_tools("请读取 README 文件并总结")
        self.assertIn("read_project_text_file", allowed)
        self.assertTrue(main.WRITE_TOOL_NAMES.isdisjoint(allowed))

    def test_computer_tools_require_matching_explicit_intent(self):
        self.assertNotIn("capture_screen", main.allowed_model_tools("你好"))
        self.assertIn("capture_screen", main.allowed_model_tools("截个屏看看"))
        self.assertIn(
            "analyze_current_screen", main.allowed_model_tools("看看屏幕上有什么")
        )
        self.assertIn("get_system_status", main.allowed_model_tools("电脑现在卡不卡"))
        self.assertIn("find_files", main.allowed_model_tools("帮我找文件"))
        self.assertIn("open_application", main.allowed_model_tools("打开 Premiere"))
        self.assertIn(
            "prepare_file_move", main.allowed_model_tools("把这个文件移动到素材目录")
        )

    def test_model_failure_uses_configured_fallback(self):
        calls = []

        class FakeCompletions:
            def create(self, **request):
                calls.append(request["model"])
                if request["model"] == "gpt-6-sol":
                    raise RuntimeError("primary unavailable")
                return "fallback-response"

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        with (
            patch.object(main, "FALLBACK_MODEL", "gpt-6-luna"),
            patch.object(main.USAGE_MANAGER, "ensure_available"),
            patch.object(main.USAGE_MANAGER, "record_response"),
        ):
            response = main.create_chat_completion_with_fallback(
                client,
                {"model": "gpt-6-sol", "messages": []},
            )
        self.assertEqual(response, "fallback-response")
        self.assertEqual(calls, ["gpt-6-sol", "gpt-6-luna"])

    def test_smart_memory_filter_skips_chitchat(self):
        self.assertFalse(main.should_analyse_memory("今天天气怎么样？", "smart"))
        self.assertFalse(main.should_analyse_memory("帮我解释一下这个概念", "smart"))

    def test_smart_memory_filter_keeps_long_term_facts(self):
        self.assertTrue(main.should_analyse_memory("我喜欢机械键盘", "smart"))
        self.assertTrue(main.should_analyse_memory("请记住以后叫我小林", "smart"))
        self.assertTrue(main.should_analyse_memory("我不再喝咖啡了", "smart"))

    def test_memory_modes_can_force_or_disable_analysis(self):
        self.assertTrue(main.should_analyse_memory("普通聊天", "always"))
        self.assertFalse(main.should_analyse_memory("请记住这件事", "off"))

    def test_static_prompt_does_not_change_with_memory(self):
        static = main.build_static_system_message("persona")
        self.assertNotIn("记忆甲", static)
        self.assertNotEqual(
            main.build_memory_message("记忆甲"), main.build_memory_message("记忆乙")
        )


if __name__ == "__main__":
    unittest.main()

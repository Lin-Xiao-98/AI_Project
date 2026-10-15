import unittest
from types import SimpleNamespace
from unittest.mock import patch

from web_search_manager import search_web


class FakeResponses:
    def __init__(self):
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        annotation = SimpleNamespace(title="示例来源", url="https://example.com")
        content = SimpleNamespace(annotations=[annotation])
        output = SimpleNamespace(content=[content])
        return SimpleNamespace(output_text="搜索结果", output=[output], usage=None)


class WebSearchManagerTests(unittest.TestCase):
    def test_search_uses_low_context_and_preserves_answer(self):
        responses = FakeResponses()
        client = SimpleNamespace(responses=responses)
        with patch("web_search_manager.USAGE_MANAGER"):
            result = search_web(client, "今天有什么新消息？")
        self.assertIn("https://example.com", result)
        self.assertEqual(
            responses.request["tools"][0]["search_context_size"], "low"
        )


if __name__ == "__main__":
    unittest.main()

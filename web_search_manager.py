"""按需调用 OpenAI 官方网页搜索，并保留可点击来源链接。"""

from __future__ import annotations

import os
import threading
import time

from usage_manager import USAGE_MANAGER

WEB_SEARCH_MODEL = os.getenv("WEB_SEARCH_MODEL", "gpt-4.1-mini")
WEB_SEARCH_CACHE_SECONDS = max(int(os.getenv("WEB_SEARCH_CACHE_SECONDS", "300")), 0)
_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_LOCK = threading.Lock()


def search_web(client, query: str, max_completion_tokens: int = 900) -> str:
    query = str(query).strip()
    if not query:
        raise ValueError("联网搜索内容不能为空。")
    if len(query) > 1000:
        raise ValueError("单次联网搜索内容不能超过 1000 个字符。")
    normalised_query = " ".join(query.casefold().split())
    cache_key = f"{WEB_SEARCH_MODEL}:{max_completion_tokens}:{normalised_query}"
    if WEB_SEARCH_CACHE_SECONDS:
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] <= WEB_SEARCH_CACHE_SECONDS:
            return cached[1]
    USAGE_MANAGER.ensure_available()
    response = client.responses.create(
        model=WEB_SEARCH_MODEL,
        tools=[{"type": "web_search", "search_context_size": "low"}],
        tool_choice={"type": "web_search"},
        include=["web_search_call.action.sources"],
        instructions=(
            "用简体中文回答。优先使用可靠的一手来源；清楚区分事实与推断；"
            "保留模型生成的内联引用。回答简洁，不超过 700 字。"
        ),
        input=query,
        max_output_tokens=max_completion_tokens,
    )
    USAGE_MANAGER.record_response(response, WEB_SEARCH_MODEL, "web_search")
    content = str(getattr(response, "output_text", "") or "").strip()
    if not content:
        raise RuntimeError("联网搜索没有返回结果。")
    sources = []
    for output in getattr(response, "output", []) or []:
        action = getattr(output, "action", None)
        for source in getattr(action, "sources", []) or []:
            url = getattr(source, "url", "")
            title = getattr(source, "title", "") or "来源"
            if url and url not in content and url not in {entry[1] for entry in sources}:
                sources.append((title, url))
        for item in getattr(output, "content", []) or []:
            for annotation in getattr(item, "annotations", []) or []:
                url = getattr(annotation, "url", "")
                title = getattr(annotation, "title", "") or "来源"
                if url and url not in content and url not in {entry[1] for entry in sources}:
                    sources.append((title, url))
    if sources:
        content += "\n\n来源：\n" + "\n".join(
            f"- [{title}]({url})" for title, url in sources[:6]
        )
    if WEB_SEARCH_CACHE_SECONDS:
        with _CACHE_LOCK:
            _CACHE[cache_key] = (time.monotonic(), content)
            if len(_CACHE) > 100:
                oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
                _CACHE.pop(oldest, None)
    return content

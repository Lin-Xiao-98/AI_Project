"""外部消息通道。

当前仅支持企业微信群机器人的官方 Webhook 主动推送。个人微信的非官方
自动登录方案存在封号和隐私风险，因此不会在这里启用。
"""

from __future__ import annotations

import json
import os
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


class WeComWebhookChannel:
    """企业微信群机器人文本推送；Webhook 始终只从环境变量读取。"""

    def __init__(self, webhook_url: str | None = None, timeout: int = 10):
        self._webhook_url = (webhook_url or os.getenv("WECOM_WEBHOOK_URL", "")).strip()
        self.timeout = timeout
        if self._webhook_url:
            self._validate_url(self._webhook_url)

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "qyapi.weixin.qq.com"
            or parsed.path != "/cgi-bin/webhook/send"
            or not query.get("key")
        ):
            raise ValueError("企业微信 Webhook 地址格式不正确。")

    @property
    def configured(self) -> bool:
        return bool(self._webhook_url)

    def status_text(self) -> str:
        return "已配置" if self.configured else "未配置（当前不会向外发送消息）"

    def send_text(self, content: str) -> None:
        if not self.configured:
            raise RuntimeError("尚未在 .env 中配置 WECOM_WEBHOOK_URL。")
        content = str(content).strip()
        if not content:
            raise ValueError("发送内容不能为空。")
        if len(content.encode("utf-8")) > 2000:
            raise ValueError("企业微信单条文本消息不能超过 2000 字节。")

        payload = json.dumps(
            {"msgtype": "text", "text": {"content": content}},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            self._webhook_url,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if result.get("errcode") != 0:
            raise RuntimeError(
                f"企业微信发送失败：{result.get('errmsg', '未知错误')}"
            )

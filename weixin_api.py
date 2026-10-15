"""腾讯微信 ClawBot iLink HTTP 通道的最小安全客户端。

协议字段与腾讯维护的 openclaw-weixin 官方插件保持兼容；本模块只负责
二维码登录、长轮询收消息和发送文字，不读取桌面微信数据库或注入微信进程。
"""

from __future__ import annotations

import base64
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
CLIENT_VERSION = "2.4.10"
CLIENT_VERSION_NUMBER = (2 << 16) | (4 << 8) | 10
APP_ID = "bot"
BOT_TYPE = "3"


class WeixinApiError(RuntimeError):
    """微信 iLink 请求失败。"""


def _safe_base_url(value: str | None) -> str:
    value = (value or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("微信通道只接受 HTTPS 地址。")
    if not (
        parsed.hostname == "ilinkai.weixin.qq.com"
        or parsed.hostname.endswith(".weixin.qq.com")
    ):
        raise ValueError("微信通道地址不是腾讯 iLink 官方域名。")
    return value


def _base_headers() -> dict[str, str]:
    random_uin = str(secrets.randbits(32)).encode("ascii")
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": base64.b64encode(random_uin).decode("ascii"),
        "iLink-App-Id": APP_ID,
        "iLink-App-ClientVersion": str(CLIENT_VERSION_NUMBER),
    }


class WeixinApi:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: str | None = None,
        timeout: float = 15.0,
        long_poll_timeout: float = 40.0,
    ):
        self.base_url = _safe_base_url(base_url)
        self.token = token.strip() if token else None
        self.timeout = timeout
        self.long_poll_timeout = long_poll_timeout

    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _request_json(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        headers = _base_headers()
        if authenticated:
            if not self.token:
                raise WeixinApiError("微信通道缺少本地登录凭证。")
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url(endpoint), data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout or self.timeout
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise WeixinApiError(f"微信服务器 HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise WeixinApiError(f"微信服务器网络连接失败：{error}") from error
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as error:
            raise WeixinApiError("微信服务器返回了无法识别的数据。") from error
        if not isinstance(result, dict):
            raise WeixinApiError("微信服务器返回格式不正确。")
        return result

    def get_qrcode(self, local_token_list: list[str] | None = None):
        query = urllib.parse.urlencode({"bot_type": BOT_TYPE})
        return self._request_json(
            "POST",
            f"ilink/bot/get_bot_qrcode?{query}",
            {"local_token_list": local_token_list or []},
            timeout=self.timeout,
        )

    def get_qrcode_status(self, qrcode: str, verify_code: str | None = None):
        query = {"qrcode": qrcode}
        if verify_code:
            query["verify_code"] = verify_code
        endpoint = "ilink/bot/get_qrcode_status?" + urllib.parse.urlencode(query)
        return self._request_json("GET", endpoint, timeout=self.long_poll_timeout)

    def get_updates(self, updates_buf: str = ""):
        return self._request_json(
            "POST",
            "ilink/bot/getupdates",
            {
                "get_updates_buf": updates_buf,
                "base_info": {
                    "channel_version": CLIENT_VERSION,
                    "bot_agent": "AIProject/1.0",
                },
            },
            timeout=self.long_poll_timeout,
            authenticated=True,
        )

    def send_text(self, to_user_id: str, text: str, context_token: str):
        if not context_token:
            raise WeixinApiError("微信回复缺少 context_token，已阻止发送。")
        return self._request_json(
            "POST",
            "ilink/bot/sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": f"aiproject-{secrets.token_hex(12)}",
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                    "context_token": context_token,
                }
            },
            timeout=self.timeout,
            authenticated=True,
        )

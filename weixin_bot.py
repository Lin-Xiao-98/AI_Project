"""个人微信 ClawBot 入口：扫码绑定后，将消息交给现有 AI_Project 核心。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv

from assistant_service import AssistantService
from main import PROJECT_DIR
from weixin_api import DEFAULT_BASE_URL, WeixinApi, WeixinApiError

load_dotenv(PROJECT_DIR / ".env")
DATA_DIR = PROJECT_DIR / "data"
STATE_FILE = DATA_DIR / "weixin_account.json"
MAX_REPLY_BYTES = 10000


@dataclass
class WeixinAccount:
    token: str
    bot_id: str
    owner_user_id: str
    base_url: str = DEFAULT_BASE_URL
    updates_buf: str = ""


def load_account(path: Path = STATE_FILE) -> WeixinAccount | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        account = WeixinAccount(**data)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("个人微信本地登录状态损坏，请重新登录。") from error
    if not account.token or not account.bot_id or not account.owner_user_id:
        raise RuntimeError("个人微信本地登录状态缺少必要字段，请重新登录。")
    return account


def save_account(account: WeixinAccount, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix="weixin_account_", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(asdict(account), stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _open_login_qr(qrcode_url: str) -> None:
    print("请用手机微信扫描下面的官方 ClawBot 二维码：")
    print(qrcode_url)
    try:
        webbrowser.open(qrcode_url)
        print("二维码已尝试在电脑默认浏览器打开。")
    except Exception:
        print("浏览器未能自动打开，请复制上面的链接到浏览器。")


def login() -> WeixinAccount:
    api = WeixinApi()
    response = api.get_qrcode()
    qrcode = str(response.get("qrcode", "")).strip()
    qrcode_url = str(response.get("qrcode_img_content", "")).strip()
    if not qrcode or not qrcode_url:
        raise RuntimeError("微信服务器没有返回有效二维码。")
    _open_login_qr(qrcode_url)
    deadline = time.monotonic() + 300
    verify_code = None
    current_api = api
    while time.monotonic() < deadline:
        try:
            status = current_api.get_qrcode_status(qrcode, verify_code)
        except WeixinApiError as error:
            print(f"二维码状态查询暂时失败，将自动重试：{error}")
            time.sleep(2)
            continue
        state = str(status.get("status", ""))
        if state == "wait":
            time.sleep(1)
            continue
        if state == "scaned":
            print("手机已扫码，正在等待微信确认……")
        elif state == "need_verifycode":
            verify_code = input("请输入手机微信显示的数字：").strip()
        elif state == "scaned_but_redirect":
            redirect_host = str(status.get("redirect_host", "")).strip()
            if redirect_host:
                current_api = WeixinApi(f"https://{redirect_host}")
        elif state == "expired":
            print("二维码已过期，正在生成新的二维码……")
            return login()
        elif state == "verify_code_blocked":
            raise RuntimeError("微信验证数字多次错误，请稍后重新启动个人微信助手。")
        elif state == "confirmed":
            account = WeixinAccount(
                token=str(status.get("bot_token", "")),
                bot_id=str(status.get("ilink_bot_id", "")),
                owner_user_id=str(status.get("ilink_user_id", "")),
                base_url=str(status.get("baseurl") or DEFAULT_BASE_URL),
            )
            if not account.token or not account.bot_id or not account.owner_user_id:
                raise RuntimeError("微信确认成功，但服务器返回的登录信息不完整。")
            account.base_url = current_api.base_url if not status.get("baseurl") else account.base_url
            save_account(account)
            print("个人微信官方 ClawBot 已绑定，登录凭证只保存在 D 盘 data 目录。")
            return account
        time.sleep(1)
    raise RuntimeError("二维码登录等待超时，请重新启动个人微信助手。")


def extract_text(message: dict) -> str:
    parts = []
    for item in message.get("item_list") or []:
        if item.get("type") == 1:
            text = (item.get("text_item") or {}).get("text", "")
            if text:
                parts.append(str(text))
        elif item.get("type") == 3:
            text = (item.get("voice_item") or {}).get("text", "")
            parts.append(str(text) if text else "[语音]")
        elif item.get("type") == 2:
            parts.append("[图片]")
        elif item.get("type") == 4:
            parts.append("[文件]")
        elif item.get("type") == 5:
            parts.append("[视频]")
    return "\n".join(part.strip() for part in parts if part.strip())


def limit_reply(text: str) -> str:
    encoded = str(text).encode("utf-8")
    if len(encoded) <= MAX_REPLY_BYTES:
        return str(text)
    suffix = "\n\n[回复过长，已安全截断]"
    budget = MAX_REPLY_BYTES - len(suffix.encode("utf-8"))
    return encoded[:budget].decode("utf-8", errors="ignore") + suffix


def run() -> None:
    if os.getenv("WEIXIN_ENABLED", "false").strip().lower() != "true":
        raise RuntimeError("个人微信通道默认关闭，请在 .env 设置 WEIXIN_ENABLED=true。")
    account = load_account() or login()
    api = WeixinApi(account.base_url, account.token)
    service = AssistantService()
    print("个人微信 AI 助手已连接。保持此窗口打开，按 Ctrl+C 停止。")
    while True:
        response = api.get_updates(account.updates_buf)
        ret = response.get("ret", 0)
        errcode = response.get("errcode", 0)
        if ret not in (0, None) or errcode not in (0, None):
            if ret == -14 or errcode == -14:
                raise RuntimeError("个人微信登录凭证已过期，请删除 data\\weixin_account.json 后重新扫码。")
            print(f"微信消息轮询失败：ret={ret} errcode={errcode} {response.get('errmsg', '')}")
            time.sleep(3)
            continue
        next_buf = response.get("get_updates_buf")
        if isinstance(next_buf, str) and next_buf:
            account.updates_buf = next_buf
            save_account(account)
        for message in response.get("msgs") or []:
            message_id = str(message.get("message_id") or "").strip()
            from_user = str(message.get("from_user_id") or "").strip()
            context_token = str(message.get("context_token") or "").strip()
            if not message_id or from_user != account.owner_user_id:
                continue
            if message.get("group_id"):
                continue
            content = extract_text(message)
            if not content or not context_token:
                continue
            if not service.conversations.claim_channel_message("weixin", message_id):
                continue
            try:
                reply = service.respond(
                    "weixin", f"{account.bot_id}:{from_user}", content, False
                )
                api.send_text(from_user, limit_reply(reply), context_token)
                service.conversations.complete_channel_message("weixin", message_id)
                # 记忆分析沿用项目的 smart 策略，并在后台执行，避免阻塞微信回复。
                threading.Thread(
                    target=service.remember, args=(content,), daemon=True
                ).start()
            except Exception as error:
                service.conversations.release_channel_message("weixin", message_id)
                print(f"个人微信消息处理失败：{error}")


if __name__ == "__main__":
    try:
        run()
    except (KeyboardInterrupt, EOFError):
        print("个人微信助手已停止。")
    except RuntimeError as error:
        print(f"启动失败：{error}")

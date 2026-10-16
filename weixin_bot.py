"""个人微信 ClawBot 入口：扫码绑定后，将消息交给现有 AI_Project 核心。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv

from assistant_service import AssistantService
from main import PROJECT_DIR
from secret_store import get_secret, set_secret
from single_instance import SingleInstance
from voice_manager import synthesize_speech
from weixin_api import DEFAULT_BASE_URL, WeixinApi, WeixinApiError
from weixin_media import download_media_items
from weixin_upload import upload_media

load_dotenv(PROJECT_DIR / ".env")
DATA_DIR = PROJECT_DIR / "data"
STATE_FILE = DATA_DIR / "weixin_account.json"
MAX_REPLY_BYTES = 10000
VOICE_REPLY_SETTING = "weixin_voice_replies"
VOICE_MAX_CHARS = 700
VOICE_TEST_TEXT = (
    "你回来啦？我刚刚还在想，你是不是又忙得忘记休息了。"
    "先喝口水嘛，剩下的事情交给我，我会乖乖帮你处理好的。"
    "还有呀，今天也要记得夸我一下，不然我可要偷偷不开心咯。"
)


@dataclass
class WeixinAccount:
    token: str
    bot_id: str
    owner_user_id: str
    base_url: str = DEFAULT_BASE_URL
    updates_buf: str = ""
    last_context_token: str = ""


def load_account(path: Path = STATE_FILE) -> WeixinAccount | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if path.resolve() == STATE_FILE.resolve():
            legacy_token = str(data.pop("token", "")).strip()
            token = get_secret("weixin_bot_token") or legacy_token
            if legacy_token:
                set_secret("weixin_bot_token", legacy_token)
            data["token"] = token or ""
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
            data = asdict(account)
            if path.resolve() == STATE_FILE.resolve():
                if get_secret("weixin_bot_token") != account.token:
                    set_secret("weixin_bot_token", account.token)
                data.pop("token", None)
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
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


def voice_intent(text: str) -> str | None:
    """识别少量明确的语音控制表达，不用模型、不产生额外 API 调用。"""
    normalized = re.sub(r"\s+", "", str(text)).lower()
    if normalized in {
        "/语音开启",
        "/语音打开",
        "开启语音回复",
        "打开语音回复",
        "以后用语音回复我",
        "以后都用语音回复我",
    }:
        return "on"
    if normalized in {
        "/语音关闭",
        "关闭语音回复",
        "以后用文字回复我",
        "以后都用文字回复我",
    }:
        return "off"
    if normalized in {"/语音状态", "语音回复状态", "现在是语音回复吗"}:
        return "status"
    if normalized in {"/语音气泡测试", "测试微信语音气泡", "测试语音气泡"}:
        return "bubble_test"
    if normalized in {
        "/语音试听",
        "给我发段语音试试",
        "给我发一段语音",
        "让我听听你的声音",
    }:
        return "once_test"
    if re.match(r"^(请|麻烦|宝宝|可以|能不能|你能不能)?用语音(回复|回答)", normalized):
        return "once"
    return None


def _voice_filename(path: Path) -> str:
    return f"小林AI助手_AI语音_{path.stem.removeprefix('speech_')}.mp3"


def send_audio_file(api, account, path: Path, context_token: str) -> None:
    uploaded = upload_media(api, path, account.owner_user_id, media_type=3)
    api.send_file(
        account.owner_user_id,
        uploaded,
        _voice_filename(path),
        context_token,
    )


def _audio_duration_ms(path: Path) -> int:
    try:
        import soundfile as sf

        info = sf.info(path)
        if info.duration > 0:
            return max(1, round(info.duration * 1000))
    except Exception:
        pass
    return 3000


def send_voice_bubble_test(api, service, account, context_token: str) -> Path:
    """尝试 iLink 原生 VOICE；腾讯当前可能接受请求但不在客户端展示。"""
    path = synthesize_speech(service.client, VOICE_TEST_TEXT)
    uploaded = upload_media(api, path, account.owner_user_id, media_type=4)
    api.send_voice_experimental(
        account.owner_user_id,
        uploaded,
        context_token,
        playtime_ms=_audio_duration_ms(path),
    )
    return path


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
            account.last_context_token = context_token
            save_account(account)
            if not service.conversations.claim_channel_message("weixin", message_id):
                continue
            try:
                try:
                    attachments = download_media_items(message)
                except Exception as error:
                    attachments = []
                    print(f"微信媒体下载失败，继续处理文字：{error}")
                intent = voice_intent(content)
                if intent == "on":
                    service.conversations.set_setting(VOICE_REPLY_SETTING, "on")
                    reply = "好呀，以后我会优先给你发 AI 生成的语音回复。需要文字时直接告诉我就好。"
                    api.send_text(from_user, reply, context_token)
                elif intent == "off":
                    service.conversations.set_setting(VOICE_REPLY_SETTING, "off")
                    reply = "好，已经切回文字回复。想听语音时直接说“用语音回复我”就可以。"
                    api.send_text(from_user, reply, context_token)
                elif intent == "status":
                    enabled = service.conversations.get_setting(
                        VOICE_REPLY_SETTING, "off"
                    ) == "on"
                    reply = f"语音回复目前{'已开启' if enabled else '未开启'}。"
                    api.send_text(from_user, reply, context_token)
                elif intent == "bubble_test":
                    path = send_voice_bubble_test(api, service, account, context_token)
                    service.conversations.set_setting(
                        "weixin_last_voice_path", str(path)
                    )
                    reply = (
                        "我刚刚尝试发送了一条原生语音气泡。腾讯 iLink 目前可能会显示，"
                        "也可能静默丢弃；如果上方没有语音条，告诉我“没看到语音”，"
                        "我会立即改发可播放的 AI 语音文件。"
                    )
                    api.send_text(from_user, reply, context_token)
                elif "没看到语音" in content or "没有语音" in content:
                    saved = service.conversations.get_setting(
                        "weixin_last_voice_path", ""
                    )
                    path = Path(saved) if saved else None
                    if path and path.is_file():
                        send_audio_file(api, account, path, context_token)
                        reply = "已经改发为可播放的 AI 语音文件。"
                    else:
                        reply = "上次的试听文件已经不存在，请发“给我发段语音试试”。"
                        api.send_text(from_user, reply, context_token)
                elif intent == "once_test":
                    path = synthesize_speech(service.client, VOICE_TEST_TEXT)
                    service.conversations.set_setting(
                        "weixin_last_voice_path", str(path)
                    )
                    send_audio_file(api, account, path, context_token)
                    reply = "已发送 AI 生成的语音试听。"
                else:
                    reply = service.respond(
                        "weixin",
                        f"{account.bot_id}:{from_user}",
                        content,
                        False,
                        attachments,
                    )
                    persistent_voice = service.conversations.get_setting(
                        VOICE_REPLY_SETTING, "off"
                    ) == "on"
                    if intent == "once" or persistent_voice:
                        try:
                            spoken = reply
                            path = synthesize_speech(
                                service.client, spoken[:VOICE_MAX_CHARS]
                            )
                            service.conversations.set_setting(
                                "weixin_last_voice_path", str(path)
                            )
                            send_audio_file(api, account, path, context_token)
                            if len(spoken) > VOICE_MAX_CHARS:
                                api.send_text(
                                    from_user,
                                    "语音只读了前一部分，完整内容如下：\n" + limit_reply(reply),
                                    context_token,
                                )
                        except Exception as voice_error:
                            print(f"微信语音生成或发送失败，已回退文字：{voice_error}")
                            api.send_text(from_user, limit_reply(reply), context_token)
                    else:
                        api.send_text(from_user, limit_reply(reply), context_token)
                service.conversations.complete_channel_message("weixin", message_id)
                # 语音开关已单独持久化，不再重复消耗一次记忆分析请求。
                if intent is None:
                    threading.Thread(
                        target=service.remember, args=(content,), daemon=True
                    ).start()
            except Exception as error:
                service.conversations.release_channel_message("weixin", message_id)
                print(f"个人微信消息处理失败：{error}")
        if account.last_context_token:
            for reminder in service.reminders.claim_remote_due():
                try:
                    api.send_text(
                        account.owner_user_id,
                        f"AI 助手提醒：{reminder['title']}",
                        account.last_context_token,
                    )
                    service.reminders.mark_remote_notified(reminder["id"])
                except Exception as error:
                    print(f"个人微信提醒发送失败，将稍后重试：{error}")
        if account.last_context_token and service.proactive.is_due():
            try:
                proactive_message = service.proactive.compose(service.client)
                api.send_text(
                    account.owner_user_id,
                    limit_reply(proactive_message),
                    account.last_context_token,
                )
                service.proactive.record_sent()
            except Exception as error:
                service.proactive.record_failure()
                print(f"主动消息发送失败，将稍后重试：{error}")


if __name__ == "__main__":
    try:
        with SingleInstance("weixin_bot"):
            run()
    except (KeyboardInterrupt, EOFError):
        print("个人微信助手已停止。")
    except RuntimeError as error:
        print(f"启动失败：{error}")
        raise SystemExit(1)

"""企业微信官方智能机器人 WebSocket 长连接入口。"""

from __future__ import annotations

import asyncio
import os
import time

from dotenv import load_dotenv

from assistant_service import AssistantService
from main import PROJECT_DIR

load_dotenv(PROJECT_DIR / ".env")


def load_wecom_config():
    enabled = os.getenv("WECOM_ENABLED", "false").strip().lower() == "true"
    bot_id = os.getenv("WECOM_BOT_ID", "").strip()
    secret = os.getenv("WECOM_BOT_SECRET", "").strip()
    allowed_users = {
        item.strip()
        for item in os.getenv("WECOM_ALLOWED_USER_IDS", "").split(",")
        if item.strip()
    }
    if not enabled:
        raise RuntimeError("企业微信长连接未启用；请先在 .env 设置 WECOM_ENABLED=true。")
    if not bot_id or not secret:
        raise RuntimeError("缺少 WECOM_BOT_ID 或 WECOM_BOT_SECRET。")
    if len(allowed_users) != 1:
        raise RuntimeError("个人助手必须且只能配置一个 WECOM_ALLOWED_USER_IDS 所有者。")
    return bot_id, secret, allowed_users


def limit_reply(text, max_bytes=10000):
    encoded = str(text).encode("utf-8")
    if len(encoded) <= max_bytes:
        return str(text)
    suffix = "\n\n[回复过长，已安全截断]"
    budget = max_bytes - len(suffix.encode("utf-8"))
    return encoded[:budget].decode("utf-8", errors="ignore") + suffix


def extract_message(frame, message_type):
    body = frame.get("body", {})
    user_id = body.get("from", {}).get("userid", "").strip()
    message_id = str(body.get("msgid", "")).strip()
    chat_type = body.get("chattype", "single")
    chat_id = body.get("chatid", "")
    content = body.get(message_type, {}).get("content", "").strip()
    subject = f"{chat_type}:{chat_id or user_id}:{user_id}"
    if not user_id or not message_id or not content:
        raise ValueError("企业微信消息缺少用户、消息编号或文字内容。")
    return user_id, message_id, subject, content


def run_wecom_bot():
    from aibot import WSClient, WSClientOptions, generate_req_id

    bot_id, secret, allowed_users = load_wecom_config()
    service = AssistantService()
    ws_client = WSClient(
        WSClientOptions(
            bot_id=bot_id,
            secret=secret,
            max_reconnect_attempts=-1,
        )
    )
    owner_id = next(iter(allowed_users))
    reminder_task = None
    processing_lock = asyncio.Lock()
    last_request_at = 0.0
    background_tasks = set()

    async def reminder_loop():
        while True:
            try:
                reminders = service.reminders.claim_remote_due()
                for reminder in reminders:
                    try:
                        await ws_client.send_message(
                            owner_id,
                            {
                                "msgtype": "markdown",
                                "markdown": {
                                    "content": f"**AI 助手提醒**\n{reminder['title']}"
                                },
                            },
                        )
                        service.reminders.mark_remote_notified(reminder["id"])
                    except Exception as error:
                        print(f"企业微信提醒发送失败，稍后重试：{error}")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                print(f"企业微信提醒检查失败，稍后重试：{error}")
            await asyncio.sleep(15)

    async def handle_message(frame, message_type):
        nonlocal last_request_at
        try:
            user_id, message_id, subject, content = extract_message(
                frame, message_type
            )
        except ValueError:
            return
        stream_id = generate_req_id("stream")
        if user_id not in allowed_users:
            await ws_client.reply_stream(
                frame, stream_id, "此账号不在助手白名单中。", True
            )
            return
        if frame.get("body", {}).get("chattype") != "single":
            await ws_client.reply_stream(
                frame, stream_id, "为保护私人资料，个人助手仅支持与所有者单聊。", True
            )
            return
        if not service.conversations.claim_channel_message("wecom", message_id):
            return
        now = time.monotonic()
        if processing_lock.locked() or now - last_request_at < 3:
            service.conversations.release_channel_message("wecom", message_id)
            await ws_client.reply_stream(
                frame, stream_id, "上一条消息仍在处理，请稍后再试。", True
            )
            return
        last_request_at = now
        try:
            async with processing_lock:
                await ws_client.reply_stream(frame, stream_id, "正在思考中…", False)
                reply = await asyncio.to_thread(
                    service.respond, "wecom", subject, content, False
                )
                await ws_client.reply_stream(frame, stream_id, limit_reply(reply), True)
                service.conversations.complete_channel_message("wecom", message_id)
                task = asyncio.create_task(asyncio.to_thread(service.remember, content))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
        except Exception as error:
            service.conversations.release_channel_message("wecom", message_id)
            print(f"企业微信消息处理失败：{error}")
            await ws_client.reply_stream(frame, stream_id, "这次处理失败了，请稍后重试。", True)

    @ws_client.on("authenticated")
    def on_authenticated():
        nonlocal reminder_task
        print("企业微信智能机器人已连接。")
        if reminder_task is None or reminder_task.done():
            reminder_task = asyncio.create_task(reminder_loop())

    @ws_client.on("message.text")
    async def on_text(frame):
        await handle_message(frame, "text")

    @ws_client.on("message.voice")
    async def on_voice(frame):
        await handle_message(frame, "voice")

    print("正在连接企业微信智能机器人……按 Ctrl+C 停止。")
    ws_client.run()


if __name__ == "__main__":
    try:
        run_wecom_bot()
    except (KeyboardInterrupt, EOFError):
        print("企业微信智能机器人已停止。")
    except RuntimeError as error:
        print(f"启动失败：{error}")

"""让终端和外部通道复用同一套助手核心能力。"""

from __future__ import annotations

import base64
import mimetypes
import threading

from action_manager import ActionManager
from backup_manager import create_backup_with_retention
from conversation_manager import ConversationManager
from knowledge_manager import KnowledgeManager
from main import (
    DEFAULT_MODE,
    MAX_HISTORY_MESSAGES,
    MODEL_PROFILES,
    allowed_model_tools,
    analyse_memory_action,
    apply_memory_action,
    build_memory_message,
    build_static_system_message,
    create_client,
    get_assistant_reply,
    load_persona,
    should_analyse_memory,
)
from memory_manager import get_memory_text
from proactive_manager import ProactiveManager
from reminder_manager import ReminderManager
from task_manager import TaskManager
from usage_manager import USAGE_MANAGER
from web_search_manager import search_web


class AssistantService:
    """面向可信外部通道的同步消息处理服务。"""

    def __init__(self, model_mode=DEFAULT_MODE):
        if model_mode not in MODEL_PROFILES:
            raise ValueError("模型档位必须是 fast、balanced 或 deep。")
        self.client = create_client()
        self.persona = load_persona()
        self.conversations = ConversationManager()
        self.tasks = TaskManager()
        self.actions = ActionManager()
        self.reminders = ReminderManager()
        self.knowledge = KnowledgeManager()
        self.proactive = ProactiveManager()
        self.model_mode = model_mode
        self._lock = threading.Lock()

    def respond(self, channel, subject, user_input, process_memory=True, attachments=None):
        user_input = str(user_input).strip()
        if not user_input:
            raise ValueError("消息内容不能为空。")
        if len(user_input) > 8000:
            raise ValueError("消息过长，请控制在 8000 个字符以内。")
        try:
            command_reply = self._remote_command(user_input)
        except (ValueError, RuntimeError) as error:
            return f"命令未执行：{error}"
        if command_reply is not None:
            return command_reply
        if user_input.startswith("/"):
            return (
                "暂不支持这个命令。常用命令：/状态、/联网 问题、"
                "/todo list、/remind list、/memory、/knowledge list、"
                "/主动消息 状态。"
            )

        with self._lock:
            session_id = self.conversations.get_or_create_scoped_session(
                channel, subject
            )
            history = self.conversations.load_messages(
                session_id, limit=MAX_HISTORY_MESSAGES
            )
            memory_text = get_memory_text()
            user_content = self._content_with_attachments(user_input, attachments or [])
            messages = [
                {
                    "role": "system",
                    "content": build_static_system_message(self.persona),
                },
                {"role": "system", "content": build_memory_message(memory_text)},
                *history,
                {"role": "user", "content": user_content},
            ]
            reply = get_assistant_reply(
                self.client,
                messages,
                self.tasks,
                self.actions,
                self.reminders,
                self.knowledge,
                MODEL_PROFILES[self.model_mode],
                allowed_model_tools(user_input),
            )
            self.conversations.add_message(session_id, "user", user_input)
            self.conversations.add_message(session_id, "assistant", reply)
            if process_memory and should_analyse_memory(user_input):
                self._remember(user_input, memory_text)
            return reply

    def _content_with_attachments(self, text, attachments):
        if not attachments:
            return text
        enriched = text
        images = []
        for attachment in attachments:
            path = attachment.path
            if attachment.kind == "image" and path.stat().st_size <= 10 * 1024 * 1024:
                mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                images.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{encoded}", "detail": "low"},
                    }
                )
            elif attachment.kind == "file" and path.suffix.lower() in {
                ".csv",
                ".docx",
                ".md",
                ".pdf",
                ".txt",
                ".xlsx",
            }:
                try:
                    extracted = self.knowledge._extract_text(path)
                    enriched += f"\n\n[附件 {path.name} 的内容]\n{extracted[:12000]}"
                except (OSError, ValueError):
                    enriched += f"\n\n[附件 {path.name} 无法提取文字]"
            else:
                enriched += f"\n\n[已安全保存附件：{path.name}]"
        return [{"type": "text", "text": enriched}, *images]

    def _remote_command(self, text):
        if text == "/状态":
            usage = USAGE_MANAGER.summary()
            proactive = self.proactive.status()
            return (
                "AI 助手运行正常。\n"
                f"今日 API：{usage['day_requests']}/{usage['daily_requests']} 次，"
                f"{usage['day_tokens']}/{usage['daily_tokens']} tokens\n"
                f"主动消息：{'开启' if proactive['enabled'] else '关闭'}；"
                f"安静时段 {proactive['quiet_hours']}"
            )
        if text.startswith("/联网 "):
            return search_web(self.client, text.removeprefix("/联网 ").strip())
        if text == "/todo list":
            tasks = self.tasks.list_tasks()
            return "待办事项：\n" + (
                "\n".join(f"- #{item['id']} {item['title']}" for item in tasks)
                if tasks
                else "目前没有未完成待办。"
            )
        if text.startswith("/todo add "):
            task_id = self.tasks.add_task(text.removeprefix("/todo add ").strip())
            return f"已添加待办 #{task_id}。"
        if text == "/remind list":
            reminders = self.reminders.list_reminders()
            return "提醒事项：\n" + (
                "\n".join(
                    f"- #{item['id']} {item['due_local']} {item['title']}"
                    for item in reminders
                )
                if reminders
                else "目前没有待发送提醒。"
            )
        if text.startswith("/remind add "):
            payload = text.removeprefix("/remind add ").strip()
            if "|" not in payload:
                return "格式：/remind add 2026-10-16 18:30|提醒内容"
            due_time, title = (part.strip() for part in payload.split("|", 1))
            reminder_id = self.reminders.add_reminder(title, due_time)
            return f"已添加提醒 #{reminder_id}。"
        if text == "/memory":
            memory = get_memory_text()
            return (memory or "目前没有长期记忆。")[:8000]
        if text == "/knowledge list":
            documents = self.knowledge.list_documents()
            return "本地资料：\n" + (
                "\n".join(
                    f"- #{item['id']} [{item['project']}] {item['title']}"
                    for item in documents
                )
                if documents
                else "资料库为空。"
            )
        if text == "/pending":
            actions = self.actions.list_pending()
            return "待审批动作：\n" + (
                "\n".join(f"- #{item['id']} {item['summary']}" for item in actions)
                if actions
                else "目前没有待审批动作。"
            )
        if text.startswith("/approve "):
            action_id = int(text.removeprefix("/approve ").strip())
            path = self.actions.approve(action_id)
            return f"已批准并创建：{path.name}"
        if text.startswith("/reject "):
            action_id = int(text.removeprefix("/reject ").strip())
            return "已拒绝。" if self.actions.reject(action_id) else "未找到待审批动作。"
        if text == "/backup":
            path = create_backup_with_retention()
            return f"备份完成：{path.name}（保存在 D 盘 backups 目录）"
        if text in {"/主动消息 开启", "/proactive on"}:
            self.proactive.set_enabled(True)
            return "主动消息已开启：每天最多 1 条，安静时段不会打扰你。"
        if text in {"/主动消息 关闭", "/proactive off"}:
            self.proactive.set_enabled(False)
            return "主动消息已关闭。你随时可以用“/主动消息 开启”恢复。"
        if text in {"/主动消息 状态", "/proactive status"}:
            status = self.proactive.status()
            return (
                f"主动消息：{'开启' if status['enabled'] else '关闭'}\n"
                f"安静时段：{status['quiet_hours']}\n"
                f"每日上限：{status['daily_limit']} 条\n"
                f"下次候选时间：{status['next_due']}"
            )
        return None

    def remember(self, user_input):
        if not should_analyse_memory(user_input):
            return
        with self._lock:
            self._remember(str(user_input).strip(), get_memory_text())

    def _remember(self, user_input, memory_text):
        try:
            memory_result = analyse_memory_action(self.client, user_input, memory_text)
            apply_memory_action(memory_result)
        except Exception:
            pass

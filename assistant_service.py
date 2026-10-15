"""让终端和外部通道复用同一套助手核心能力。"""

from __future__ import annotations

import threading

from action_manager import ActionManager
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
from reminder_manager import ReminderManager
from task_manager import TaskManager


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
        self.model_mode = model_mode
        self._lock = threading.Lock()

    def respond(self, channel, subject, user_input, process_memory=True):
        user_input = str(user_input).strip()
        if not user_input:
            raise ValueError("消息内容不能为空。")
        if len(user_input) > 8000:
            raise ValueError("消息过长，请控制在 8000 个字符以内。")
        if user_input.startswith("/"):
            return "远程通道暂不执行斜杠命令；管理和审批请在本机终端完成。"

        with self._lock:
            session_id = self.conversations.get_or_create_scoped_session(
                channel, subject
            )
            history = self.conversations.load_messages(
                session_id, limit=MAX_HISTORY_MESSAGES
            )
            memory_text = get_memory_text()
            messages = [
                {
                    "role": "system",
                    "content": build_static_system_message(self.persona),
                },
                {"role": "system", "content": build_memory_message(memory_text)},
                *history,
                {"role": "user", "content": user_input},
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

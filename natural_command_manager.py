"""把少量明确中文表达转换为本地任务/提醒操作。

规则故意保持窄范围：只有明显的祈使句才会写入，普通聊天不会误触；解析完全本地完成。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta


def _clean_title(value: str) -> str:
    return value.strip(" ，,。.!！?？:：")


def _find_unique_item(items, title: str):
    """按完整标题优先、唯一包含其次查找，避免含糊命令误操作。"""
    wanted = _clean_title(title).casefold()
    exact = [item for item in items if item["title"].strip().casefold() == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [item for item in items if wanted in item["title"].strip().casefold()]
    return partial[0] if len(partial) == 1 else None


def _parse_chinese_time(value: str, now: datetime | None = None):
    now = now or datetime.now().astimezone()
    value = re.sub(r"\s+", "", value)

    absolute = re.fullmatch(
        r"(?P<year>\d{4})[-/年](?P<month>\d{1,2})[-/月](?P<day>\d{1,2})日?"
        r"(?P<period>上午|早上|中午|下午|晚上)?"
        r"(?P<hour>\d{1,2})(?:[:点时](?P<minute>\d{1,2})?分?)?(?P<half>半)?",
        value,
    )
    if absolute:
        parts = absolute.groupdict()
        hour = int(parts["hour"])
        minute = 30 if parts["half"] else int(parts["minute"] or 0)
        if parts["period"] in {"下午", "晚上"} and hour < 12:
            hour += 12
        if parts["period"] == "中午" and hour < 11:
            hour += 12
        try:
            return now.replace(
                year=int(parts["year"]),
                month=int(parts["month"]),
                day=int(parts["day"]),
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            return None

    relative = re.fullmatch(
        r"(?P<day>今天|明天|后天|今晚|明早|明晚)"
        r"(?P<period>上午|早上|中午|下午|晚上)?"
        r"(?P<hour>\d{1,2})(?:[:点时](?P<minute>\d{1,2})?分?)?(?P<half>半)?",
        value,
    )
    if not relative:
        return None
    parts = relative.groupdict()
    day_token = parts["day"]
    days = 0 if day_token in {"今天", "今晚"} else 1 if day_token in {"明天", "明早", "明晚"} else 2
    hour = int(parts["hour"])
    minute = 30 if parts["half"] else int(parts["minute"] or 0)
    period = parts["period"]
    if day_token in {"今晚", "明晚"}:
        period = "晚上"
    elif day_token == "明早":
        period = "早上"
    if period in {"下午", "晚上"} and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    try:
        target = (now + timedelta(days=days)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    except ValueError:
        return None
    return target


def _extract_reminder(text: str, now: datetime | None = None):
    time_pattern = (
        r"(?:\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?"
        r"(?:上午|早上|中午|下午|晚上)?\d{1,2}(?:[:点时]\d{0,2}分?)?半?"
        r"|(?:今天|明天|后天|今晚|明早|明晚)"
        r"(?:上午|早上|中午|下午|晚上)?\d{1,2}(?:[:点时]\d{0,2}分?)?半?)"
    )
    patterns = (
        rf"^(?:请|麻烦)?(?:在)?(?P<when>{time_pattern})提醒我(?P<title>.+)$",
        rf"^(?:请|麻烦)?提醒我(?:在)?(?P<when>{time_pattern})(?P<title>.+)$",
    )
    compact = re.sub(r"\s+", "", text.strip())
    for pattern in patterns:
        match = re.fullmatch(pattern, compact)
        if not match:
            continue
        target = _parse_chinese_time(match.group("when"), now)
        title = _clean_title(match.group("title"))
        if target and title:
            return target, title
    return None


def handle_natural_command(
    text, tasks, reminders, now: datetime | None = None, actions=None
):
    """执行明确自然语言命令；不是命令时返回 None。"""
    original = str(text).strip()
    compact = re.sub(r"\s+", "", original)

    if compact in {"查看待办", "看看待办", "我有哪些待办", "列出待办", "待办事项"}:
        items = tasks.list_tasks()
        return "待办事项：\n" + (
            "\n".join(f"- #{item['id']} {item['title']}" for item in items)
            if items
            else "目前没有未完成待办。"
        )

    task_patterns = (
        r"^(?:请|麻烦|帮我)?(?:添加|新增|创建|记下|记个)(?:一个|一条)?(?:待办|任务)[：:,，]?(?P<title>.+)$",
        r"^(?:请|麻烦|帮我)?把(?P<title>.+?)(?:加入|添加到)(?:待办|任务)(?:里|中)?$",
    )
    for pattern in task_patterns:
        match = re.fullmatch(pattern, compact)
        if match:
            title = _clean_title(match.group("title"))
            if title:
                task_id = tasks.add_task(title)
                return f"已帮你添加待办 #{task_id}：{title}"

    match = re.fullmatch(r"(?:完成|办完)(?:待办|任务)?#?(?P<id>\d+)", compact)
    if match:
        return "待办已完成。" if tasks.complete_task(match.group("id")) else "没有找到这条未完成待办。"

    match = re.fullmatch(
        r"(?:完成|办完|做完)(?:待办|任务)[：:,，]?(?P<title>.+)", compact
    )
    if match:
        item = _find_unique_item(tasks.list_tasks(), match.group("title"))
        if item is None:
            return "没有找到唯一匹配的未完成待办，请说完整任务名称。"
        tasks.complete_task(item["id"])
        return f"待办已完成：{item['title']}"

    match = re.fullmatch(
        r"(?:删除|取消)(?:待办|任务)#?(?P<id>\d+)", compact
    )
    if match:
        return "待办已删除。" if tasks.delete_task(match.group("id")) else "没有找到这条待办。"

    match = re.fullmatch(
        r"(?:删除|取消)(?:待办|任务)[：:,，]?(?P<title>.+)", compact
    )
    if match:
        item = _find_unique_item(tasks.list_tasks(), match.group("title"))
        if item is None:
            return "没有找到唯一匹配的待办，请说完整任务名称。"
        tasks.delete_task(item["id"])
        return f"待办已删除：{item['title']}"

    reminder = _extract_reminder(original, now)
    if reminder:
        target, title = reminder
        due = target.strftime("%Y-%m-%d %H:%M")
        reminder_id = reminders.add_reminder(title, due)
        return f"已帮你添加提醒 #{reminder_id}：{due}，{title}"

    if compact in {"查看提醒", "看看提醒", "我有哪些提醒", "列出提醒", "提醒事项"}:
        items = reminders.list_reminders()
        return "提醒事项：\n" + (
            "\n".join(
                f"- #{item['id']} {item['due_local']} {item['title']}" for item in items
            )
            if items
            else "目前没有待发送提醒。"
        )

    match = re.fullmatch(r"(?:完成|处理完)提醒#?(?P<id>\d+)", compact)
    if match:
        return "提醒已完成。" if reminders.complete_reminder(match.group("id")) else "没有找到这条提醒。"

    match = re.fullmatch(r"(?:删除|取消)提醒#?(?P<id>\d+)", compact)
    if match:
        return "提醒已删除。" if reminders.delete_reminder(match.group("id")) else "没有找到这条提醒。"

    match = re.fullmatch(r"(?:删除|取消)提醒[：:,，]?(?P<title>.+)", compact)
    if match:
        item = _find_unique_item(reminders.list_reminders(), match.group("title"))
        if item is None:
            return "没有找到唯一匹配的提醒，请说完整提醒内容。"
        reminders.delete_reminder(item["id"])
        return f"提醒已删除：{item['title']}"

    if actions is not None:
        if compact in {"查看待审批", "查看待审批操作", "有哪些待审批操作"}:
            items = actions.list_pending()
            return "待审批动作：\n" + (
                "\n".join(f"- #{item['id']} {item['summary']}" for item in items)
                if items
                else "目前没有待审批动作。"
            )
        match = re.fullmatch(
            r"(?:批准|同意执行)(?:操作|动作)?#?(?P<id>[0-9a-fA-F]{12})",
            compact,
        )
        if match:
            path = actions.approve(match.group("id"))
            return f"已批准并创建：{path.name}"
        match = re.fullmatch(
            r"(?:拒绝|不同意)(?:操作|动作)?#?(?P<id>[0-9a-fA-F]{12})",
            compact,
        )
        if match:
            return "已拒绝。" if actions.reject(match.group("id")) else "没有找到待审批动作。"

    return None


import json
from datetime import datetime
from pathlib import Path

from conversation_manager import PROJECT_DIR

AUDIT_FILE = PROJECT_DIR / "data" / "tool_audit.jsonl"
MAX_FILE_BYTES = 100_000
MAX_LISTED_FILES = 200
BLOCKED_PARTS = {
    ".git",
    ".env",
    "venv",
    "__pycache__",
    "data",
    "memory.json",
}
READABLE_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".csv",
}


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "联网检索最新或可能变化的信息，并返回带来源链接的答案。仅在本地知识和常识不足时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "具体、简洁的搜索问题。"}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "检索用户已经明确导入本地资料库的文本片段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要查找的关键词。"},
                    "project": {"type": "string", "description": "项目名；不限定时为空字符串。"},
                },
                "required": ["query", "project"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "读取运行此助手的电脑当前本地日期和时间。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_project_files",
            "description": "列出 AI_Project 授权目录内的文件。不会读取 .env、Git、虚拟环境或私人数据库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "相对于 AI_Project 的目录；根目录使用空字符串。",
                    }
                },
                "required": ["directory"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_project_text_file",
            "description": "读取 AI_Project 授权目录内的小型文本文件。禁止读取 .env、Git、虚拟环境和私人数据库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于 AI_Project 根目录的文本文件路径。",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "读取用户保存在本地的任务清单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_done": {
                        "type": "boolean",
                        "description": "是否同时包含已经完成的任务。",
                    }
                },
                "required": ["include_done"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "在用户明确要求记录待办事项时，向本地任务清单新增一项。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "清晰、简短的任务内容。",
                    }
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_workspace_file",
            "description": "准备在 workspace 目录中新建文本文件。只创建待审批动作；用户必须用 /approve 编号确认后才会写入。禁止覆盖。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于 workspace 的文件路径，例如 notes/idea.md。",
                    },
                    "content": {
                        "type": "string",
                        "description": "准备写入的新文件完整内容。",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_reminder",
            "description": "用户明确要求在未来具体时间收到提醒时，新增一个本地文字提醒。不会播放声音。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "提醒内容。"},
                    "due_time": {
                        "type": "string",
                        "description": "本地时间，格式 YYYY-MM-DD HH:MM。",
                    },
                },
                "required": ["title", "due_time"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
]

# 用户已明确授权项目目录内的非敏感文本只读。敏感路径仍由
# _safe_project_path 永久拦截，不会作为工具结果发送给模型。
MODEL_TOOL_DEFINITIONS = [
    definition
    for definition in TOOL_DEFINITIONS
    if definition["function"]["name"] not in {"add_task", "add_reminder"}
]


def _safe_project_path(relative_path, expect_directory=False):
    if not isinstance(relative_path, str):
        raise ValueError("路径必须是文本")

    relative = Path(relative_path or ".")
    if relative.is_absolute():
        raise ValueError("只允许使用项目内的相对路径")

    candidate = (PROJECT_DIR / relative).resolve()
    try:
        candidate.relative_to(PROJECT_DIR.resolve())
    except ValueError as error:
        raise ValueError("路径超出了 AI_Project 授权目录") from error

    relative_parts = candidate.relative_to(PROJECT_DIR.resolve()).parts
    if any(
        part in BLOCKED_PARTS or part.startswith(".env")
        for part in relative_parts
    ):
        raise ValueError("这个路径包含受保护内容，不能通过工具读取")

    if not candidate.exists():
        raise ValueError("路径不存在")
    if expect_directory and not candidate.is_dir():
        raise ValueError("指定路径不是目录")
    return candidate


def _list_project_files(directory):
    base = _safe_project_path(directory, expect_directory=True)
    files = []
    for path in sorted(base.rglob("*")):
        if len(files) >= MAX_LISTED_FILES:
            break
        if not path.is_file():
            continue
        relative = path.relative_to(PROJECT_DIR)
        if any(
            part in BLOCKED_PARTS or part.startswith(".env")
            for part in relative.parts
        ):
            continue
        files.append(str(relative).replace("\\", "/"))
    return {"files": files, "truncated": len(files) >= MAX_LISTED_FILES}


def _read_project_text_file(path):
    target = _safe_project_path(path)
    if not target.is_file():
        raise ValueError("指定路径不是文件")
    if target.suffix.lower() not in READABLE_SUFFIXES:
        raise ValueError("只允许读取常见文本文件")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("文件超过 100 KB，拒绝整份读取")
    return {
        "path": str(target.relative_to(PROJECT_DIR)).replace("\\", "/"),
        "content": target.read_text(encoding="utf-8"),
    }


def _write_audit(name, arguments, success, error=None):
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": name,
        "arguments": arguments,
        "success": success,
    }
    if error:
        record["error"] = error
    with open(AUDIT_FILE, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def execute_tool(
    name,
    arguments,
    task_manager,
    action_manager=None,
    reminder_manager=None,
    knowledge_manager=None,
    client=None,
):
    """执行白名单工具，并将每次尝试写入本地审计日志。"""
    if not isinstance(arguments, dict):
        raise ValueError("工具参数必须是 JSON 对象")

    try:
        if name == "search_web":
            if client is None:
                raise ValueError("联网搜索客户端尚未初始化")
            from web_search_manager import search_web

            result = {"answer": search_web(client, arguments["query"])}
        elif name == "get_current_time":
            result = {
                "local_time": datetime.now().astimezone().isoformat(timespec="seconds")
            }
        elif name == "list_project_files":
            result = _list_project_files(arguments["directory"])
        elif name == "read_project_text_file":
            result = _read_project_text_file(arguments["path"])
        elif name == "list_tasks":
            result = {
                "tasks": task_manager.list_tasks(arguments["include_done"])
            }
        elif name == "add_task":
            title = arguments["title"].strip()
            existing = next(
                (
                    task
                    for task in task_manager.list_tasks()
                    if task["title"].strip().casefold() == title.casefold()
                ),
                None,
            )
            result = (
                {"task_id": existing["id"], "added": False}
                if existing
                else {"task_id": task_manager.add_task(title), "added": True}
            )
        elif name == "prepare_workspace_file":
            if action_manager is None:
                raise ValueError("文件审批管理器尚未初始化")
            result = action_manager.prepare_file_creation(
                arguments["path"], arguments["content"]
            )
        elif name == "add_reminder":
            if reminder_manager is None:
                raise ValueError("提醒管理器尚未初始化")
            title = arguments["title"].strip()
            due_time = arguments["due_time"].strip()
            existing = next(
                (
                    reminder
                    for reminder in reminder_manager.list_reminders()
                    if reminder["title"].strip().casefold() == title.casefold()
                    and reminder["due_local"] == due_time
                ),
                None,
            )
            result = (
                {"reminder_id": existing["id"], "added": False}
                if existing
                else {
                    "reminder_id": reminder_manager.add_reminder(title, due_time),
                    "added": True,
                }
            )
        elif name == "search_knowledge":
            if knowledge_manager is None:
                raise ValueError("资料库尚未初始化")
            result = {
                "results": knowledge_manager.search(
                    arguments["query"], arguments["project"]
                )
            }
        else:
            raise ValueError(f"未注册的工具：{name}")
    except Exception as error:
        _write_audit(name, arguments, False, str(error))
        raise

    _write_audit(name, arguments, True)
    return json.dumps(result, ensure_ascii=False)

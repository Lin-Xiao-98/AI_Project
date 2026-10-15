"""不联网、不播放声音的本地验收检查。"""

import json
import os
import sqlite3
import sys

from dotenv import load_dotenv

from conversation_manager import DEFAULT_DATABASE, PROJECT_DIR
from memory_manager import MEMORY_FILE, get_memory_count
from secret_store import get_secret


def check(label, passed, detail=""):
    mark = "通过" if passed else "失败"
    suffix = f"：{detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")
    return passed


def main():
    load_dotenv(PROJECT_DIR / ".env")
    results = []
    results.append(
        check("Python 版本", sys.version_info >= (3, 11), sys.version.split()[0])
    )
    api_key = get_secret("openai_api_key", "OPENAI_API_KEY") or ""
    has_key = bool(api_key and api_key != "your_api_key_here")
    results.append(check("OpenAI API Key", has_key, "已配置" if has_key else "未配置"))

    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            results.append(
                check("私人长期记忆", isinstance(data, dict), f"{get_memory_count()} 条")
            )
        except Exception as error:
            results.append(check("私人长期记忆", False, str(error)))
    else:
        results.append(check("私人长期记忆", True, "将在首次保存时创建"))

    if DEFAULT_DATABASE.exists():
        try:
            connection = sqlite3.connect(DEFAULT_DATABASE)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                connection.close()
            results.append(check("本地数据库", integrity == "ok", integrity))
        except Exception as error:
            results.append(check("本地数据库", False, str(error)))
    else:
        results.append(check("本地数据库", True, "将在首次启动时创建"))

    required_files = (
        "main.py",
        "memory_manager.py",
        "voice_manager.py",
        "wecom_bot.py",
        "assistant_guardian.py",
        "assistant_dashboard.py",
        "启动AI助手.bat",
    )
    missing = [name for name in required_files if not (PROJECT_DIR / name).exists()]
    results.append(
        check("核心文件", not missing, "完整" if not missing else ", ".join(missing))
    )

    wecom_enabled = os.getenv("WECOM_ENABLED", "false").lower() == "true"
    if wecom_enabled:
        try:
            from aibot import WSClient  # noqa: F401

            from wecom_bot import load_wecom_config

            load_wecom_config()
            results.append(check("企业微信长连接", True, "已启用"))
        except Exception as error:
            results.append(check("企业微信长连接", False, str(error)))
    else:
        results.append(check("企业微信长连接", True, "安全关闭"))

    print("\n验收结果：", "全部通过" if all(results) else "存在失败项")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

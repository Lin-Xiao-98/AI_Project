"""把 .env 中的明文密钥安全迁移到 Windows DPAPI。"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from dotenv import dotenv_values

from conversation_manager import PROJECT_DIR
from secret_store import get_secret, set_secret

ENV_FILE = PROJECT_DIR / ".env"


def set_env_value(name: str, value: str, env_file: Path = ENV_FILE) -> None:
    """原子更新一项普通配置，不读取或打印其他配置值。"""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(name)):
        raise ValueError("配置名格式无效")
    value = str(value)
    if "\n" in value or "\r" in value:
        raise ValueError("配置值不能包含换行")
    env_file = Path(env_file)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    original = (
        env_file.read_text(encoding="utf-8").splitlines(keepends=True)
        if env_file.exists()
        else []
    )
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=")
    replacement = f"{name}={value}\n"
    updated = []
    replaced = False
    for line in original:
        if not pattern.match(line):
            updated.append(line)
        elif not replaced:
            updated.append(replacement)
            replaced = True
    if not replaced:
        if updated and not updated[-1].endswith(("\n", "\r")):
            updated[-1] += "\n"
        updated.append(replacement)
    descriptor, temp_name = tempfile.mkstemp(
        prefix="env_", suffix=".tmp", dir=env_file.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.writelines(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, env_file)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def migrate_env_secret(
    env_name: str = "OPENAI_API_KEY",
    secret_name: str = "openai_api_key",
    env_file: Path = ENV_FILE,
) -> bool:
    env_file = Path(env_file)
    if not env_file.exists():
        return False
    value = str(dotenv_values(env_file).get(env_name) or "").strip()
    if not value or value == "your_api_key_here":
        return False
    set_secret(secret_name, value)
    if get_secret(secret_name) != value:
        raise RuntimeError("密钥迁移校验失败，原文件未改变。")

    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(env_name)}\s*=")
    original = env_file.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in original if not pattern.match(line)]
    descriptor, temp_name = tempfile.mkstemp(
        prefix="env_", suffix=".tmp", dir=env_file.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.writelines(kept)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, env_file)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return True


if __name__ == "__main__":
    migrated = migrate_env_secret()
    print("OpenAI 密钥已安全迁移。" if migrated else "无需迁移 OpenAI 密钥。")

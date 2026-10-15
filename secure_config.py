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

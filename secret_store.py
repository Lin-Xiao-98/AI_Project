"""使用 Windows DPAPI 保存本机当前用户才能解密的项目密钥。"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

from conversation_manager import PROJECT_DIR

SECRET_FILE = PROJECT_DIR / "data" / "secrets.json"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _protect(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("安全密钥库仅支持 Windows DPAPI。")
    source, source_buffer = _blob(value.encode("utf-8"))
    output = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "AI_Project", None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return base64.b64encode(
            ctypes.string_at(output.pbData, output.cbData)
        ).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer


def _unprotect(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("安全密钥库仅支持 Windows DPAPI。")
    source, source_buffer = _blob(base64.b64decode(value, validate=True))
    output = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer


def _load(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("本地安全密钥库损坏。") from error
    if not isinstance(data, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in data.items()
    ):
        raise RuntimeError("本地安全密钥库格式错误。")
    return data


def _save(data: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix="secrets_", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def set_secret(name: str, value: str, path: Path = SECRET_FILE) -> None:
    name = str(name).strip()
    value = str(value).strip()
    if not name or not value:
        raise ValueError("密钥名称和值不能为空。")
    path = Path(path)
    data = _load(path)
    data[name] = _protect(value)
    _save(data, path)


def get_secret(
    name: str, env_name: str | None = None, path: Path = SECRET_FILE
) -> str | None:
    encrypted = _load(Path(path)).get(name)
    if encrypted:
        try:
            return _unprotect(encrypted)
        except (OSError, ValueError, UnicodeError) as error:
            raise RuntimeError(f"无法解密本地密钥：{name}") from error
    if env_name:
        value = os.getenv(env_name, "").strip()
        return value or None
    return None


def delete_secret(name: str, path: Path = SECRET_FILE) -> bool:
    path = Path(path)
    data = _load(path)
    if name not in data:
        return False
    del data[name]
    _save(data, path)
    return True

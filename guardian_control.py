"""后台守护程序的启动、停止和状态读取。"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
from pathlib import Path

from conversation_manager import PROJECT_DIR

TASK_NAME = "小林AI助手-个人微信后台"
STATUS_FILE = PROJECT_DIR / "data" / "guardian_status.json"
STARTUP_SHORTCUT = (
    Path(os.getenv("APPDATA", ""))
    / "Microsoft/Windows/Start Menu/Programs/Startup/小林AI助手后台.lnk"
)


def _run(arguments: list[str], check: bool = True):
    return subprocess.run(
        arguments,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _process_command_line(pid) -> str:
    if not isinstance(pid, int) or pid <= 0:
        return ""
    return _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine",
        ],
        check=False,
    ).stdout.strip()


def _pid_running(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0 or os.name != "nt":
        return False
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def read_status() -> dict:
    if not STATUS_FILE.exists():
        return {"state": "not_started", "detail": "尚未启动"}
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"state": "unknown", "detail": "状态文件无法读取"}
    if not isinstance(data, dict):
        return {"state": "unknown"}
    if data.get("state") in {"running", "restarting"} and not _pid_running(
        data.get("guardian_pid")
    ):
        return {**data, "state": "stopped", "detail": "后台进程已经结束"}
    return data


def start_guardian() -> None:
    result = _run(["schtasks.exe", "/Run", "/TN", TASK_NAME], check=False)
    if not result.returncode:
        return
    pythonw = PROJECT_DIR / "venv" / "Scripts" / "pythonw.exe"
    subprocess.Popen(
        [str(pythonw), str(PROJECT_DIR / "assistant_guardian.py")],
        cwd=PROJECT_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=(
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
    )


def stop_guardian() -> None:
    status = read_status()
    pid = status.get("guardian_pid")
    if isinstance(pid, int) and pid > 0:
        command = _process_command_line(pid)
        if "assistant_guardian.py" in command:
            _run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], check=False)
    _run(["schtasks.exe", "/End", "/TN", TASK_NAME], check=False)


def install_autostart() -> None:
    pythonw = PROJECT_DIR / "venv" / "Scripts" / "pythonw.exe"
    guardian = PROJECT_DIR / "assistant_guardian.py"
    if not pythonw.exists():
        raise RuntimeError("找不到 D 盘虚拟环境中的 pythonw.exe。")
    command = f'"{pythonw}" "{guardian}"'
    result = _run(
        [
            "schtasks.exe",
            "/Create",
            "/F",
            "/SC",
            "ONLOGON",
            "/TN",
            TASK_NAME,
            "/TR",
            command,
        ],
        check=False,
    )
    if not result.returncode:
        return
    STARTUP_SHORTCUT.parent.mkdir(parents=True, exist_ok=True)
    def quote(value):
        return str(value).replace("'", "''")

    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut"
        f"('{quote(STARTUP_SHORTCUT)}');"
        f"$s.TargetPath='{quote(pythonw)}';"
        f"$s.Arguments='\"{quote(guardian)}\"';"
        f"$s.WorkingDirectory='{quote(PROJECT_DIR)}';"
        "$s.WindowStyle=7;$s.Save()"
    )
    shortcut = _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            script,
        ],
        check=False,
    )
    if shortcut.returncode or not STARTUP_SHORTCUT.exists():
        detail = (shortcut.stderr or shortcut.stdout).strip()
        raise RuntimeError(f"安装登录自启动失败：{detail}")


if __name__ == "__main__":
    install_autostart()
    print(f"后台自启动已安装：{STARTUP_SHORTCUT}")

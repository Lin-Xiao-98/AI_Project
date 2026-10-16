"""受限的本机只读能力与固定白名单应用启动。

这里刻意不提供任意命令行、键盘鼠标控制、密码/剪贴板读取、删除文件，
也不会修改声音、亮度或系统安全设置。
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import psutil
from PIL import ImageGrab

from conversation_manager import PROJECT_DIR

SCREENSHOT_DIR = PROJECT_DIR / "data" / "screenshots"
MAX_FOUND_FILES = 100
SCREENSHOT_RETENTION_HOURS = 24


def _default_search_roots() -> tuple[Path, ...]:
    home = Path.home()
    candidates = [Path("D:/Workspace"), home / "Desktop", home / "Documents", home / "Downloads"]
    return tuple(path.resolve() for path in candidates if path.exists())


ALLOWED_SEARCH_ROOTS = _default_search_roots()

APPLICATION_CANDIDATES = {
    "notepad": (Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/notepad.exe",),
    "calculator": (Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/calc.exe",),
    "explorer": (Path(os.environ.get("WINDIR", "C:/Windows")) / "explorer.exe",),
    "vscode": (
        Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe",
    ),
    "premiere": (
        Path("C:/Program Files/Adobe/Adobe Premiere Pro 2025/Adobe Premiere Pro.exe"),
    ),
}


def get_system_status() -> dict:
    """返回精简系统状态，不包含窗口标题、命令行或私人内容。"""
    memory = psutil.virtual_memory()
    disks = []
    for drive in ("C:/", "D:/"):
        if not Path(drive).exists():
            continue
        usage = psutil.disk_usage(drive)
        disks.append(
            {
                "drive": drive[:2],
                "used_gb": round(usage.used / 1024**3, 1),
                "free_gb": round(usage.free / 1024**3, 1),
                "percent": usage.percent,
            }
        )
    battery = psutil.sensors_battery()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_used_gb": round(memory.used / 1024**3, 1),
        "memory_total_gb": round(memory.total / 1024**3, 1),
        "memory_percent": memory.percent,
        "disks": disks,
        "battery": None
        if battery is None
        else {
            "percent": round(battery.percent),
            "plugged_in": bool(battery.power_plugged),
        },
        "uptime_hours": round(
            (datetime.now().timestamp() - psutil.boot_time()) / 3600, 1
        ),
    }


def list_running_apps(limit: int = 30) -> dict:
    """列出资源占用较高的进程；不返回命令行和窗口标题。"""
    limit = max(1, min(int(limit), 50))
    apps = []
    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = process.info
            name = str(info.get("name") or "").strip()
            memory_info = info.get("memory_info")
            if not name or memory_info is None:
                continue
            apps.append(
                {
                    "name": name,
                    "pid": int(info["pid"]),
                    "memory_mb": round(memory_info.rss / 1024**2, 1),
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    apps.sort(key=lambda item: item["memory_mb"], reverse=True)
    return {"apps": apps[:limit], "truncated": len(apps) > limit}


def _safe_search_root(root: str) -> Path:
    if not isinstance(root, str) or not root.strip():
        raise ValueError("搜索目录不能为空")
    candidate = Path(root).expanduser().resolve()
    for allowed in ALLOWED_SEARCH_ROOTS:
        try:
            candidate.relative_to(allowed)
            break
        except ValueError:
            continue
    else:
        readable = "、".join(str(path) for path in ALLOWED_SEARCH_ROOTS)
        raise ValueError(f"这个目录未授权搜索；当前允许：{readable}")
    if not candidate.is_dir():
        raise ValueError("搜索目录不存在或不是文件夹")
    return candidate


def find_files(root: str, query: str, suffix: str = "", limit: int = 50) -> dict:
    """只按文件名搜索允许目录，不读取文件内容。"""
    base = _safe_search_root(root)
    query = str(query).strip().casefold()
    suffix = str(suffix).strip().casefold()
    if not query and not suffix:
        raise ValueError("文件名关键词和扩展名至少填写一个")
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    limit = max(1, min(int(limit), MAX_FOUND_FILES))
    blocked = {"$recycle.bin", "system volume information", ".git", "venv", "__pycache__"}
    matches = []
    for directory, names, files in os.walk(base):
        names[:] = [
            name
            for name in names
            if name.casefold() not in blocked and not name.startswith(".")
        ]
        for filename in files:
            folded = filename.casefold()
            if query and query not in folded:
                continue
            if suffix and Path(filename).suffix.casefold() != suffix:
                continue
            path = Path(directory) / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            matches.append(
                {
                    "path": str(path),
                    "size_mb": round(stat.st_size / 1024**2, 2),
                    "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="minutes"),
                }
            )
            if len(matches) >= limit:
                return {"files": matches, "truncated": True}
    return {"files": matches, "truncated": False}


def _cleanup_old_screenshots() -> None:
    cutoff = datetime.now().timestamp() - timedelta(hours=SCREENSHOT_RETENTION_HOURS).total_seconds()
    if not SCREENSHOT_DIR.exists():
        return
    for path in SCREENSHOT_DIR.glob("screen_*.png"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def capture_screen() -> dict:
    """用户明确要求时截取一次屏幕并保存到 D 盘；不会自动上传。"""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_old_screenshots()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = SCREENSHOT_DIR / f"screen_{timestamp}.png"
    image = ImageGrab.grab(all_screens=True)
    image.save(target, format="PNG")
    return {
        "path": str(target),
        "width": image.width,
        "height": image.height,
        "note": "截图只保存在本机 D 盘，尚未上传或外发。",
    }


def open_application(application: str) -> dict:
    """只启动预先核验过的固定应用，不接受路径或命令参数。"""
    key = str(application).strip().casefold()
    aliases = {
        "记事本": "notepad",
        "计算器": "calculator",
        "资源管理器": "explorer",
        "文件管理器": "explorer",
        "code": "vscode",
        "vscode": "vscode",
        "premiere": "premiere",
        "pr": "premiere",
    }
    key = aliases.get(key, key)
    candidates = APPLICATION_CANDIDATES.get(key)
    if not candidates:
        raise ValueError("这个应用不在安全启动白名单中")
    executable = next((path.resolve() for path in candidates if path.is_file()), None)
    if executable is None:
        raise ValueError("已允许这个应用，但本机没有找到它")
    subprocess.Popen(
        [str(executable)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"opened": key, "executable": executable.name}

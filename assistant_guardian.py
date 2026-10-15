"""个人微信助手后台守护：崩溃重启、日志轮转和每日备份。"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler

from backup_manager import BACKUP_DIR, create_backup_with_retention
from conversation_manager import PROJECT_DIR
from single_instance import SingleInstance

DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
STATUS_FILE = DATA_DIR / "guardian_status.json"
PID_FILE = DATA_DIR / "guardian.pid"
INBOX_DIR = DATA_DIR / "inbox"
BACKUP_INTERVAL = 24 * 60 * 60


def _logger():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("assistant_guardian")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_DIR / "guardian.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _write_status(state: str, child_pid: int | None = None, detail: str = ""):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "guardian_pid": os.getpid(),
        "child_pid": child_pid,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "detail": detail,
    }
    temporary = STATUS_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, STATUS_FILE)


def _backup_due() -> bool:
    backups = list(BACKUP_DIR.glob("ai_assistant_backup_*.zip"))
    return not backups or time.time() - max(path.stat().st_mtime for path in backups) >= BACKUP_INTERVAL


def _prune_inbox(max_age_days: int = 30) -> int:
    if not INBOX_DIR.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for path in INBOX_DIR.iterdir():
        if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def run():
    logger = _logger()
    stopping = False
    child = None

    def request_stop(_signum=None, _frame=None):
        nonlocal stopping
        stopping = True
        if child and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    with SingleInstance("assistant_guardian"):
        PID_FILE.write_text(str(os.getpid()), encoding="ascii")
        logger.info("后台守护程序启动")
        removed = _prune_inbox()
        if removed:
            logger.info("已清理 %s 个超过 30 天的微信附件", removed)
        failures = 0
        try:
            while not stopping:
                if _backup_due():
                    try:
                        backup = create_backup_with_retention()
                        logger.info("自动备份完成：%s", backup.name)
                    except Exception:
                        logger.exception("自动备份失败")

                child_log = (LOG_DIR / "weixin_bot.log").open("a", encoding="utf-8")
                try:
                    child_environment = os.environ.copy()
                    child_environment["WEIXIN_ENABLED"] = "true"
                    child = subprocess.Popen(
                        [sys.executable, str(PROJECT_DIR / "weixin_bot.py")],
                        cwd=PROJECT_DIR,
                        stdin=subprocess.DEVNULL,
                        stdout=child_log,
                        stderr=subprocess.STDOUT,
                        env=child_environment,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    _write_status("running", child.pid)
                    started = time.monotonic()
                    while not stopping and child.poll() is None:
                        if _backup_due():
                            try:
                                backup = create_backup_with_retention()
                                logger.info("自动备份完成：%s", backup.name)
                            except Exception:
                                logger.exception("自动备份失败")
                        time.sleep(5)
                    if stopping:
                        break
                    runtime = time.monotonic() - started
                    failures = 0 if runtime >= 300 else failures + 1
                    delay = min(5 * (2 ** min(failures, 5)), 300)
                    logger.warning(
                        "微信助手退出（代码 %s），%s 秒后重启", child.returncode, delay
                    )
                    _write_status("restarting", None, f"{delay} 秒后重启")
                    time.sleep(delay)
                finally:
                    child_log.close()
        finally:
            if child and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
            _write_status("stopped")
            PID_FILE.unlink(missing_ok=True)
            logger.info("后台守护程序停止")


if __name__ == "__main__":
    try:
        run()
    except RuntimeError as error:
        _write_status("duplicate", detail=str(error))

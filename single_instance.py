"""Windows 单实例文件锁。"""

from __future__ import annotations

import msvcrt

from conversation_manager import PROJECT_DIR


class SingleInstance:
    def __init__(self, name: str):
        self.path = PROJECT_DIR / "data" / f"{name}.lock"
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            self.handle.close()
            self.handle = None
            raise RuntimeError("程序已经在运行。") from error
        return self

    def __exit__(self, *_args):
        if self.handle is not None:
            self.handle.seek(0)
            try:
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self.handle.close()
                self.handle = None

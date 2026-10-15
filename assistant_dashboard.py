"""面向非技术用户的本地助手控制台。"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from backup_manager import BACKUP_DIR, create_backup_with_retention, restore_backup
from conversation_manager import PROJECT_DIR
from guardian_control import read_status, start_guardian, stop_guardian
from usage_manager import USAGE_MANAGER

DATA_DIR = PROJECT_DIR / "data"


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("小林 AI 助手控制台")
        self.geometry("560x430")
        self.resizable(False, False)
        self.configure(bg="#f5f6fa")
        self.status_text = tk.StringVar()
        self.usage_text = tk.StringVar()
        self._build()
        self.refresh()

    def _build(self):
        tk.Label(
            self,
            text="小林 AI 助手",
            font=("Microsoft YaHei UI", 20, "bold"),
            bg="#f5f6fa",
        ).pack(pady=(25, 6))
        tk.Label(
            self,
            text="个人微信后台状态",
            font=("Microsoft YaHei UI", 10),
            fg="#666666",
            bg="#f5f6fa",
        ).pack()
        tk.Label(
            self,
            textvariable=self.status_text,
            font=("Microsoft YaHei UI", 15, "bold"),
            bg="#f5f6fa",
        ).pack(pady=(6, 18))

        buttons = tk.Frame(self, bg="#f5f6fa")
        buttons.pack()
        self._button(buttons, "启动后台", self.start, 0, 0)
        self._button(buttons, "停止后台", self.stop, 0, 1)
        self._button(buttons, "立即备份", self.backup, 1, 0)
        self._button(buttons, "打开数据目录", self.open_data, 1, 1)
        self._button(buttons, "恢复备份", self.restore, 2, 0)
        self._button(buttons, "刷新状态", self.refresh, 2, 1)

        tk.Label(
            self,
            textvariable=self.usage_text,
            justify="left",
            font=("Microsoft YaHei UI", 10),
            bg="white",
            relief="solid",
            bd=1,
            padx=16,
            pady=12,
        ).pack(fill="x", padx=55, pady=22)
        tk.Label(
            self,
            text="关闭本窗口不会停止微信后台。",
            font=("Microsoft YaHei UI", 9),
            fg="#777777",
            bg="#f5f6fa",
        ).pack()

    def _button(self, parent, text, command, row, column):
        tk.Button(
            parent,
            text=text,
            command=command,
            width=15,
            height=2,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=row, column=column, padx=8, pady=7)

    def refresh(self):
        status = read_status()
        labels = {
            "running": "● 正在运行",
            "restarting": "◐ 正在自动重启",
            "stopped": "○ 已停止",
            "duplicate": "● 已有实例运行",
            "not_started": "○ 尚未启动",
        }
        self.status_text.set(labels.get(status.get("state"), "? 状态未知"))
        usage = USAGE_MANAGER.summary()
        self.usage_text.set(
            "API 安全用量（本机统计）\n"
            f"今日：{usage['day_requests']}/{usage['daily_requests']} 次，"
            f"{usage['day_tokens']}/{usage['daily_tokens']} tokens\n"
            f"本月：{usage['month_requests']}/{usage['monthly_requests']} 次，"
            f"{usage['month_tokens']}/{usage['monthly_tokens']} tokens"
        )
        self.after(5000, self.refresh)

    def start(self):
        try:
            start_guardian()
            self.after(1200, self.refresh)
        except Exception as error:
            messagebox.showerror("启动失败", str(error))

    def stop(self):
        try:
            stop_guardian()
            self.after(500, self.refresh)
        except Exception as error:
            messagebox.showerror("停止失败", str(error))

    def backup(self):
        try:
            path = create_backup_with_retention()
            messagebox.showinfo("备份完成", f"备份已保存到 D 盘：\n{path}")
        except Exception as error:
            messagebox.showerror("备份失败", str(error))

    def open_data(self):
        path = DATA_DIR if DATA_DIR.exists() else PROJECT_DIR
        os.startfile(Path(path))

    def restore(self):
        selected = filedialog.askopenfilename(
            title="选择要恢复的 AI 助手备份",
            initialdir=BACKUP_DIR,
            filetypes=[("AI 助手 ZIP 备份", "*.zip")],
        )
        if not selected:
            return
        if not messagebox.askyesno(
            "确认恢复",
            "将用所选备份替换当前记忆和数据库。恢复前会自动再备份当前状态，是否继续？",
        ):
            return
        try:
            stop_guardian()
            safety = restore_backup(selected)
            start_guardian()
            messagebox.showinfo("恢复完成", f"恢复成功。恢复前的数据已备份为：\n{safety.name}")
        except Exception as error:
            messagebox.showerror("恢复失败", str(error))


if __name__ == "__main__":
    Dashboard().mainloop()

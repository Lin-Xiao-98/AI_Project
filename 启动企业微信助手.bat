@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo 找不到项目虚拟环境，请先完成安装。
    pause
    exit /b 1
)
"venv\Scripts\python.exe" "wecom_bot.py"
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\pythonw.exe" (
    echo 找不到项目虚拟环境。
    pause
    exit /b 1
)
start "" "venv\Scripts\pythonw.exe" "assistant_dashboard.py"

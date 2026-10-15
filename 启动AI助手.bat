@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "%~dp0venv\Scripts\python.exe" (
    echo 找不到项目虚拟环境，请先安装 Python 依赖。
    pause
    exit /b 1
)

"%~dp0venv\Scripts\python.exe" "%~dp0main.py"

if errorlevel 1 (
    echo.
    echo 程序异常退出，请把上面的错误信息发给 Codex。
    pause
)

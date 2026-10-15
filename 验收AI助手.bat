@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo 找不到项目虚拟环境。
    pause
    exit /b 1
)
echo 正在运行自动化测试……
"venv\Scripts\python.exe" -m unittest discover -v
if errorlevel 1 goto failed
echo.
echo 正在检查本地数据与配置……
"venv\Scripts\python.exe" "health_check.py"
if errorlevel 1 goto failed
echo.
echo AI 助手验收全部通过。
pause
exit /b 0

:failed
echo.
echo 验收发现问题，请查看上面的失败信息。
pause
exit /b 1

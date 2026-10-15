@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" goto run_weixin
echo 找不到项目虚拟环境，请先安装 Python 依赖。
pause
exit /b 1

:run_weixin
set "WEIXIN_ENABLED=true"
"venv\Scripts\python.exe" "weixin_bot.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo 个人微信助手异常退出，请把上面的错误信息发给 Codex。
echo.
pause
exit /b %EXIT_CODE%

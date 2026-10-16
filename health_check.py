"""不联网、不播放声音的本地验收检查。"""

import json
import os
import sqlite3
import subprocess
import sys

from dotenv import load_dotenv

from conversation_manager import DEFAULT_DATABASE, PROJECT_DIR
from memory_manager import MEMORY_FILE, get_memory_count
from secret_store import get_secret

LOCAL_ASSETS = PROJECT_DIR / "local_assets"
QWEN_PYTHON = (
    LOCAL_ASSETS / "runtime" / "Qwen3-TTS" / "venv" / "Scripts" / "python.exe"
)
QWEN_MODEL = (
    LOCAL_ASSETS
    / "models"
    / "Qwen3-TTS"
    / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
)
QWEN_WEIGHTS = QWEN_MODEL / "model.safetensors"
MIN_QWEN_WEIGHTS_BYTES = 3_000_000_000
FFMPEG = LOCAL_ASSETS / "tools" / "FFmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = LOCAL_ASSETS / "tools" / "FFmpeg" / "bin" / "ffprobe.exe"


def check_local_qwen():
    required = (QWEN_PYTHON, QWEN_MODEL / "config.json", QWEN_WEIGHTS)
    missing = [str(path.relative_to(PROJECT_DIR)) for path in required if not path.exists()]
    if missing:
        return False, "缺少 " + "、".join(missing)
    if QWEN_WEIGHTS.stat().st_size < MIN_QWEN_WEIGHTS_BYTES:
        return False, "模型权重不完整，请按 docs/运行环境与恢复说明.md 重新下载"
    try:
        result = subprocess.run(
            [
                str(QWEN_PYTHON),
                "-c",
                "import torch,qwen_tts;print('cuda' if torch.cuda.is_available() else 'no-cuda')",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"本地语音环境无法启动：{error}"
    if result.returncode != 0:
        return False, "本地语音依赖损坏，请按恢复说明重建 runtime"
    if result.stdout.strip().splitlines()[-1:] != ["cuda"]:
        return False, "未检测到可用 NVIDIA CUDA，本地 Qwen 语音无法运行"
    return True, "运行环境、模型与 CUDA 正常"


def check_ffmpeg():
    missing = [path.name for path in (FFMPEG, FFPROBE) if not path.is_file()]
    if missing:
        return False, "缺少 " + "、".join(missing)
    try:
        result = subprocess.run(
            [str(FFMPEG), "-version"],
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"FFmpeg 无法启动：{error}"
    return result.returncode == 0, "工具正常" if result.returncode == 0 else "工具损坏"


def check(label, passed, detail=""):
    mark = "通过" if passed else "失败"
    suffix = f"：{detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")
    return passed


def main():
    load_dotenv(PROJECT_DIR / ".env")
    results = []
    results.append(
        check("Python 版本", sys.version_info >= (3, 11), sys.version.split()[0])
    )
    api_key = get_secret("openai_api_key", "OPENAI_API_KEY") or ""
    has_key = bool(api_key and api_key != "your_api_key_here")
    results.append(check("OpenAI API Key", has_key, "已配置" if has_key else "未配置"))

    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            results.append(
                check("私人长期记忆", isinstance(data, dict), f"{get_memory_count()} 条")
            )
        except Exception as error:
            results.append(check("私人长期记忆", False, str(error)))
    else:
        results.append(check("私人长期记忆", True, "将在首次保存时创建"))

    if DEFAULT_DATABASE.exists():
        try:
            connection = sqlite3.connect(DEFAULT_DATABASE)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                connection.close()
            results.append(check("本地数据库", integrity == "ok", integrity))
        except Exception as error:
            results.append(check("本地数据库", False, str(error)))
    else:
        results.append(check("本地数据库", True, "将在首次启动时创建"))

    required_files = (
        "main.py",
        "memory_manager.py",
        "voice_manager.py",
        "wecom_bot.py",
        "assistant_guardian.py",
        "assistant_dashboard.py",
        "diagnostics_manager.py",
        "export_manager.py",
        "启动AI助手.bat",
    )
    missing = [name for name in required_files if not (PROJECT_DIR / name).exists()]
    results.append(
        check("核心文件", not missing, "完整" if not missing else ", ".join(missing))
    )

    ffmpeg_ok, ffmpeg_detail = check_ffmpeg()
    results.append(check("本地 FFmpeg", ffmpeg_ok, ffmpeg_detail))

    tts_provider = os.getenv("TTS_PROVIDER", "qwen").strip().casefold()
    if tts_provider == "qwen":
        qwen_ok, qwen_detail = check_local_qwen()
        results.append(check("本地 Qwen 语音", qwen_ok, qwen_detail))
    else:
        results.append(check("本地 Qwen 语音", True, f"当前使用 {tts_provider}，无需本地模型"))

    weixin_enabled = os.getenv("WEIXIN_ENABLED", "false").lower() == "true"
    account_file = PROJECT_DIR / "data" / "weixin_account.json"
    token = get_secret("weixin_bot_token") or ""
    if account_file.is_file() and token:
        results.append(check("个人微信登录", True, "本机登录状态完整"))
    elif weixin_enabled:
        results.append(check("个人微信登录", False, "需重新扫码绑定"))
    else:
        results.append(check("个人微信登录", True, "尚未绑定，启用时需要扫码"))

    wecom_enabled = os.getenv("WECOM_ENABLED", "false").lower() == "true"
    if wecom_enabled:
        try:
            from aibot import WSClient  # noqa: F401

            from wecom_bot import load_wecom_config

            load_wecom_config()
            results.append(check("企业微信长连接", True, "已启用"))
        except Exception as error:
            results.append(check("企业微信长连接", False, str(error)))
    else:
        results.append(check("企业微信长连接", True, "安全关闭"))

    print("\n验收结果：", "全部通过" if all(results) else "存在失败项")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

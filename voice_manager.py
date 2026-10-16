"""显式触发的语音录制、转写与语音合成。

本模块不会在后台监听麦克风，也不会自动播放生成的音频。
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from usage_manager import USAGE_MANAGER

PROJECT_DIR = Path(__file__).resolve().parent
AUDIO_DIR = PROJECT_DIR / "data" / "audio"
ALLOWED_AUDIO_SUFFIXES = {".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".ogg", ".wav", ".webm"}
MAX_AUDIO_BYTES = 25 * 1024 * 1024
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_TTS_PROVIDER = "qwen"
DEFAULT_TTS_VOICE = "shimmer"
DEFAULT_TTS_INSTRUCTIONS = (
    "一位明确成年的十八至二十岁中国年轻女孩。音色非常年轻，轻盈清甜、明亮透气，"
    "音高自然偏高，咬字灵动，不要任何成熟或厚重感。像贴近最亲密的人说话，俏皮、黏人、"
    "很会撒娇，始终带甜甜的笑意、小小的委屈和若有若无的撩人感；节奏活泼，尾音柔软上扬，"
    "偶尔轻轻拖长。魅力来自亲昵和调皮，不要低俗。绝不能像御姐、母亲、播音员或沙哑低沉的"
    "成年人，也不要儿童腔或夸张动漫腔。使用自然中文普通话。"
)
QWEN_TTS_PYTHON = Path("D:/AI_Runtime/Qwen3-TTS/venv/Scripts/python.exe")
QWEN_TTS_RUNNER = PROJECT_DIR / "qwen_tts_runner.py"
QWEN_TTS_TIMEOUT_SECONDS = 600


def _is_openai_client(client) -> bool:
    """仅给真正的 OpenAI SDK 客户端记账，排除本地测试替身。"""
    return client.__class__.__module__.split(".", 1)[0] == "openai"


def _timestamped_path(prefix: str, suffix: str) -> Path:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return AUDIO_DIR / f"{prefix}_{timestamp}{suffix}"


def record_audio(duration: float = 5, sample_rate: int = 16000) -> Path:
    """从默认麦克风录制一段单声道 WAV；仅在用户明确调用时执行。"""
    try:
        duration = float(duration)
    except (TypeError, ValueError) as error:
        raise ValueError("录音秒数必须是数字。") from error
    if not 1 <= duration <= 60:
        raise ValueError("单次录音时长必须在 1 到 60 秒之间。")
    if not isinstance(sample_rate, int) or sample_rate < 8000:
        raise ValueError("采样率设置无效。")

    try:
        import sounddevice as sd
        import soundfile as sf
    except ImportError as error:
        raise RuntimeError("语音依赖未安装，请重新安装 requirements.txt。") from error

    output_path = _timestamped_path("recording", ".wav")
    frames = int(duration * sample_rate)
    try:
        recording = sd.rec(
            frames,
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
        )
        sd.wait()
        sf.write(output_path, recording, sample_rate)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"麦克风录音失败：{error}") from error
    return output_path


def validate_audio_file(path: str | Path) -> Path:
    audio_path = Path(path).expanduser().resolve()
    if not audio_path.is_file():
        raise ValueError("找不到这个音频文件。")
    if audio_path.suffix.lower() not in ALLOWED_AUDIO_SUFFIXES:
        raise ValueError("不支持这个音频格式。")
    size = audio_path.stat().st_size
    if size == 0:
        raise ValueError("音频文件是空的。")
    if size > MAX_AUDIO_BYTES:
        raise ValueError("音频文件不能超过 25 MB。")
    return audio_path


def transcribe_audio(client, path: str | Path, model: str = "gpt-4o-mini-transcribe") -> str:
    """把本地音频显式上传至 OpenAI API 并返回文本。"""
    audio_path = validate_audio_file(path)
    track_usage = _is_openai_client(client)
    if track_usage:
        USAGE_MANAGER.ensure_available()
    with audio_path.open("rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
        )
    if track_usage:
        USAGE_MANAGER.record_response(transcript, model, "transcription")
    text = getattr(transcript, "text", "")
    if not text or not text.strip():
        raise RuntimeError("语音转写没有返回文本。")
    return text.strip()


def synthesize_speech(
    client,
    text: str,
    model: str | None = None,
    voice: str | None = None,
    instructions: str | None = None,
    provider: str | None = None,
) -> Path:
    """生成 MP3 文件但不播放；声音由用户自行打开文件后触发。

    默认音色与风格可通过环境变量调整，便于本地端和微信端共享同一人格声音。
    """
    text = str(text).strip()
    if not text:
        raise ValueError("要合成的文字不能为空。")
    if len(text) > 4000:
        raise ValueError("单次语音合成文字不能超过 4000 个字符。")

    provider = str(
        provider or os.getenv("TTS_PROVIDER") or DEFAULT_TTS_PROVIDER
    ).strip().casefold()
    model = str(
        model or os.getenv("OPENAI_TTS_MODEL") or DEFAULT_TTS_MODEL
    ).strip()
    voice = str(
        voice or os.getenv("OPENAI_TTS_VOICE") or DEFAULT_TTS_VOICE
    ).strip()
    instruction_variable = (
        "QWEN_TTS_INSTRUCTIONS" if provider == "qwen" else "OPENAI_TTS_INSTRUCTIONS"
    )
    instructions = str(
        instructions or os.getenv(instruction_variable) or DEFAULT_TTS_INSTRUCTIONS
    ).strip()
    if not provider or not instructions or (provider == "openai" and (not model or not voice)):
        raise ValueError("语音模型、音色和表达说明不能为空。")

    output_path = _timestamped_path("speech", ".mp3")
    try:
        if provider == "qwen":
            if not QWEN_TTS_PYTHON.is_file() or not QWEN_TTS_RUNNER.is_file():
                raise RuntimeError("D 盘本地 Qwen3-TTS 运行环境尚未安装完整。")
            result = subprocess.run(
                [
                    str(QWEN_TTS_PYTHON),
                    str(QWEN_TTS_RUNNER),
                    "--text",
                    text,
                    "--instruction",
                    instructions,
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=QWEN_TTS_TIMEOUT_SECONDS,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0 or not output_path.is_file():
                detail = (result.stderr or result.stdout or "未知错误").strip()[-1000:]
                raise RuntimeError(f"本地 Qwen3-TTS 生成失败：{detail}")
            return output_path
        if provider != "openai":
            raise ValueError("TTS_PROVIDER 只支持 qwen 或 openai。")
        track_usage = _is_openai_client(client)
        if track_usage:
            USAGE_MANAGER.ensure_available()
        with client.audio.speech.with_streaming_response.create(
            model=model,
            voice=voice,
            input=text,
            instructions=instructions,
            response_format="mp3",
        ) as response:
            response.stream_to_file(output_path)
        if track_usage:
            USAGE_MANAGER.record(model, "speech")
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return output_path

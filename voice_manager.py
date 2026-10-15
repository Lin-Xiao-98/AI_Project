"""显式触发的语音录制、转写与语音合成。

本模块不会在后台监听麦克风，也不会自动播放生成的音频。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
AUDIO_DIR = PROJECT_DIR / "data" / "audio"
ALLOWED_AUDIO_SUFFIXES = {".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".ogg", ".wav", ".webm"}
MAX_AUDIO_BYTES = 25 * 1024 * 1024


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
    with audio_path.open("rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
        )
    text = getattr(transcript, "text", "")
    if not text or not text.strip():
        raise RuntimeError("语音转写没有返回文本。")
    return text.strip()


def synthesize_speech(
    client,
    text: str,
    model: str = "gpt-4o-mini-tts",
    voice: str = "marin",
) -> Path:
    """生成 MP3 文件但不播放；声音由用户自行打开文件后触发。"""
    text = str(text).strip()
    if not text:
        raise ValueError("要合成的文字不能为空。")
    if len(text) > 4000:
        raise ValueError("单次语音合成文字不能超过 4000 个字符。")

    output_path = _timestamped_path("speech", ".mp3")
    try:
        with client.audio.speech.with_streaming_response.create(
            model=model,
            voice=voice,
            input=text,
            instructions="自然、清晰、温和地使用普通话朗读。",
        ) as response:
            response.stream_to_file(output_path)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return output_path

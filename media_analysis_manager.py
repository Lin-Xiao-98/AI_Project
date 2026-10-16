"""使用 D 盘 FFmpeg 对视频做只读检查、抽帧与基础拉片报告。"""

from __future__ import annotations

import json
import math
import re
import subprocess
from datetime import datetime
from fractions import Fraction
from pathlib import Path

from conversation_manager import PROJECT_DIR

FFMPEG_DIR = PROJECT_DIR / "local_assets" / "tools" / "FFmpeg" / "bin"
FFMPEG = FFMPEG_DIR / "ffmpeg.exe"
FFPROBE = FFMPEG_DIR / "ffprobe.exe"
REPORT_ROOT = PROJECT_DIR / "workspace" / "media_reports"
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts"}
MAX_SAMPLE_FRAMES = 24


def _video_path(path: str | Path) -> Path:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("找不到视频文件")
    if source.suffix.casefold() not in VIDEO_SUFFIXES:
        raise ValueError("暂不支持这种视频格式")
    return source


def _require_tools() -> None:
    if not FFMPEG.is_file() or not FFPROBE.is_file():
        raise RuntimeError("D 盘 FFmpeg 工具尚未安装完整")


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def probe_video(path: str | Path) -> dict:
    """读取视频技术参数，不修改源文件。"""
    _require_tools()
    source = _video_path(path)
    result = _run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(source),
        ]
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    format_info = payload.get("format") or {}
    try:
        frame_rate = float(Fraction(video.get("avg_frame_rate") or "0/1"))
    except (ValueError, ZeroDivisionError):
        frame_rate = 0.0
    return {
        "path": str(source),
        "duration_seconds": round(float(format_info.get("duration") or 0), 3),
        "size_mb": round(source.stat().st_size / 1024**2, 2),
        "format": str(format_info.get("format_long_name") or format_info.get("format_name") or "未知"),
        "video_codec": str(video.get("codec_name") or "未知"),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": round(frame_rate, 3),
        "audio_codec": str(audio.get("codec_name") or "无音轨"),
        "sample_rate": int(audio.get("sample_rate") or 0),
    }


def _timecode(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def create_shot_report(path: str | Path, max_frames: int = 12) -> dict:
    """等距抽取代表帧并生成 Markdown 基础拉片，不覆盖或转码源视频。"""
    source = _video_path(path)
    metadata = probe_video(source)
    duration = metadata["duration_seconds"]
    if duration <= 0:
        raise ValueError("无法读取视频时长")
    max_frames = max(3, min(int(max_frames), MAX_SAMPLE_FRAMES))
    frame_count = min(max_frames, max(3, math.ceil(duration / 3)))
    interval = duration / frame_count
    safe_stem = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", source.stem)[:60] or "video"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = REPORT_ROOT / f"{safe_stem}_{stamp}"
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=False)

    _run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            f"fps=1/{interval:.6f},scale=960:-2",
            "-frames:v",
            str(frame_count),
            "-q:v",
            "3",
            str(frames_dir / "frame_%03d.jpg"),
        ]
    )
    frames = sorted(frames_dir.glob("frame_*.jpg"))
    lines = [
        f"# 《{source.name}》基础拉片报告",
        "",
        "> 本报告由本地 FFmpeg 只读分析生成；原视频未被修改。",
        "",
        "## 技术信息",
        "",
        f"- 时长：{_timecode(duration)}",
        f"- 画面：{metadata['width']}×{metadata['height']}，{metadata['fps']} fps，{metadata['video_codec']}",
        f"- 声音：{metadata['audio_codec']}，{metadata['sample_rate']} Hz",
        f"- 文件大小：{metadata['size_mb']} MB",
        "",
        "## 时间码与代表画面",
        "",
        "| 时间码 | 代表帧 | 镜头内容/构图/声音备注 |",
        "|---|---|---|",
    ]
    for index, frame in enumerate(frames):
        timecode = _timecode(min(index * interval, duration))
        lines.append(f"| {timecode} | ![]({frame.relative_to(output_dir).as_posix()}) | 待补充 |")
    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "可继续让助手结合这些代表帧分析叙事、景别、构图、节奏和剪辑建议。",
        ]
    )
    report = output_dir / "拉片报告.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return {"report_path": str(report), "frame_count": len(frames), "metadata": metadata}

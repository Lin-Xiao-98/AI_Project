"""Qwen3-TTS 独立运行器。

由 D 盘专用虚拟环境启动，避免把大型 AI 依赖塞进主助手环境。
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

DEFAULT_MODEL = Path("D:/AI_Models/Qwen3-TTS/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
FFMPEG = Path("D:/AI_Tools/FFmpeg/bin/ffmpeg.exe")

AUDITION_TEXT = "你终于回来啦？我都等你好久了。再不理我，我可真的要生气啦……不过，你要是好好哄哄我，我也不是不能原谅你呀。"
AUDITIONS = (
    (
        "A_轻甜俏皮",
        "一位明确成年的十八至二十岁中国年轻女孩。声线非常年轻、轻盈、清甜、透亮，音调偏高但自然，带笑意和灵动感。说话俏皮可爱、略带撒娇，语速稍快，尾音轻轻上扬。绝不能像成熟姐姐、母亲、播音员或低沉沙哑的成年人，也不要幼儿腔和夸张动漫腔。使用自然普通话。",
    ),
    (
        "B_黏人撒娇",
        "一位明确成年的十八至二十岁中国年轻女孩。音色轻软甜美、娇俏灵动、非常有少女感。像和最亲近的人私下说话，明显黏人、爱撒娇、带一点小委屈和调皮，呼吸轻柔，停顿自然，尾音柔软拖长。避免成熟、端庄、播音腔、御姐感、低音和沙哑；不要装成儿童。使用自然普通话。",
    ),
    (
        "C_俏皮魅惑湘鄂",
        "一位明确成年的十八至二十岁中国年轻女孩。声线年轻、轻柔、甜而清亮，带亲昵笑意和若有若无的撩人感；俏皮、黏人、会撒娇，语气近距离、略带气声，但保持自然克制。加入很轻微的湖北通城、崇阳靠岳阳方向的湘鄂交界口音，只做语调点缀，不能显老、不能乡土化。绝不使用成熟御姐、母亲、播音或沙哑低沉音色，也不要儿童腔。",
    ),
)


def _load_model(model_path: Path):
    if not model_path.is_dir():
        raise RuntimeError(f"找不到本地 Qwen3-TTS 模型：{model_path}")
    if not torch.cuda.is_available():
        raise RuntimeError("Qwen3-TTS 需要 NVIDIA CUDA，但当前环境没有检测到 GPU")
    return Qwen3TTSModel.from_pretrained(
        str(model_path),
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )


def _write_mp3(waveform, sample_rate: int, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        wav = Path(temporary) / "speech.wav"
        sf.write(wav, waveform, sample_rate)
        subprocess.run(
            [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(wav),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "160k",
                str(output),
            ],
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def generate_one(model, text: str, instruction: str, output: Path, seed: int = 20261020):
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    waveforms, sample_rate = model.generate_voice_design(
        text=text,
        language="Chinese",
        instruct=instruction,
        max_new_tokens=2048,
    )
    _write_mp3(waveforms[0], sample_rate, output)


def generate_auditions(model, output_dir: Path) -> list[Path]:
    outputs = []
    for index, (name, instruction) in enumerate(AUDITIONS, start=1):
        output = output_dir / f"{name}.mp3"
        generate_one(model, AUDITION_TEXT, instruction, output, seed=20261016 + index)
        outputs.append(output)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--text")
    parser.add_argument("--instruction")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audition-dir", type=Path)
    parser.add_argument("--seed", type=int, default=20261020)
    args = parser.parse_args()
    model = _load_model(args.model)
    if args.audition_dir:
        for path in generate_auditions(model, args.audition_dir):
            print(path)
        return
    if not args.text or not args.instruction or not args.output:
        parser.error("单次生成需要 --text、--instruction 和 --output")
    generate_one(model, args.text, args.instruction, args.output, args.seed)
    print(args.output)


if __name__ == "__main__":
    main()

import shutil
import subprocess
from pathlib import Path
from typing import Callable

import soundfile as sf
import torch
from demucs.separate import main as demucs_separate

ProgressCallback = Callable[[int, str], None]


def convert_to_wav(input_path: Path, output_path: Path) -> None:
    if input_path.suffix.lower() == ".wav":
        shutil.copy2(input_path, output_path)
        return

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")


def separate_audio(
    input_path: Path,
    job_dir: Path,
    report_progress: ProgressCallback,
) -> dict[str, str | float]:
    input_dir = job_dir / "input"
    exports = job_dir / "exports"
    input_dir.mkdir(parents=True, exist_ok=True)
    exports.mkdir(parents=True, exist_ok=True)

    audio_wav = input_dir / "track.wav"
    report_progress(10, "Preparing audio")
    convert_to_wav(input_path, audio_wav)

    report_progress(30, "Separating vocals")
    demucs_separate(
        [
            "--two-stems",
            "vocals",
            "-o",
            str(job_dir),
            "-n",
            "htdemucs",
            "--device",
            "cuda" if torch.cuda.is_available() else "cpu",
            str(audio_wav),
        ]
    )

    stem_dir = job_dir / "htdemucs" / audio_wav.stem
    vocals = stem_dir / "vocals.wav"
    instrumental = stem_dir / "no_vocals.wav"
    if not vocals.exists() or not instrumental.exists():
        raise RuntimeError("Separated stems are missing")

    report_progress(90, "Saving stems")
    vocals_out = exports / "vocals.wav"
    instrumental_out = exports / "instrumental.wav"
    shutil.copy2(vocals, vocals_out)
    shutil.copy2(instrumental, instrumental_out)

    try:
        duration = float(sf.info(str(instrumental_out)).duration)
    except Exception:
        duration = 0.0

    return {
        "duration": duration,
        "instrumental_path": str(instrumental_out),
        "vocals_path": str(vocals_out),
    }

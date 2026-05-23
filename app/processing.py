import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable

import soundfile as sf
import torch
from demucs.separate import main as demucs_separate

from app import config

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


def get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    # Note: 'mps' is disabled on macOS due to a known PyTorch reflection padding assertion bug in Demucs.
    return "cpu"


def get_audio_duration(path: Path) -> float:
    try:
        import subprocess
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            return float(probe.stdout.strip())
    except Exception:
        pass
    try:
        import soundfile as sf
        return float(sf.info(str(path)).duration)
    except Exception:
        return 0.0


def separate_audio(
    input_path: Path,
    job_dir: Path,
    report_progress: ProgressCallback,
) -> dict[str, str | float]:
    input_dir = job_dir / "input"
    exports = job_dir / "exports"
    input_dir.mkdir(parents=True, exist_ok=True)
    exports.mkdir(parents=True, exist_ok=True)

    vocals_out = exports / "vocals.mp3"
    instrumental_out = exports / "instrumental.mp3"
    if config.truthy_env("REUSE_PROCESSED_OUTPUTS", True) and outputs_are_ready(
        instrumental_out,
        vocals_out,
    ):
        report_progress(95, "Already processed, reusing saved stems")
        return result_payload(instrumental_out, vocals_out)

    audio_wav = input_dir / "track.wav"
    report_progress(10, "Preparing audio")
    convert_to_wav(input_path, audio_wav)

    report_progress(30, "Separating vocals")
    
    # Configure CPU threading limits and GPU devices
    device = get_device()
    if device == "cpu":
        torch.set_num_threads(min(4, torch.get_num_threads()))

    demucs_separate(
        [
            "--two-stems",
            "vocals",
            "-o",
            str(job_dir),
            "-n",
            "htdemucs",
            "--device",
            device,
            str(audio_wav),
        ]
    )

    report_progress(90, "Saving stems")
    
    stem_dir = job_dir / "htdemucs" / audio_wav.stem
    vocals_wav = stem_dir / "vocals.wav"
    instrumental_wav = stem_dir / "no_vocals.wav"
    if not vocals_wav.exists() or not instrumental_wav.exists():
        raise RuntimeError("Separated stems are missing")

    # Convert separated stems directly to high-fidelity MP3 in exports directory
    convert_wav_to_mp3(vocals_wav, vocals_out)
    convert_wav_to_mp3(instrumental_wav, instrumental_out)

    if not outputs_are_ready(instrumental_out, vocals_out):
        raise RuntimeError("Separated stems are empty")

    # Clean up all WAV and intermediate files immediately to eliminate WAV storage
    shutil.rmtree(job_dir / "htdemucs", ignore_errors=True)
    try:
        audio_wav.unlink(missing_ok=True)
    except Exception:
        pass

    return result_payload(instrumental_out, vocals_out)


def outputs_are_ready(instrumental_path: Path, vocals_path: Path) -> bool:
    return (
        instrumental_path.exists()
        and vocals_path.exists()
        and instrumental_path.stat().st_size > 0
        and vocals_path.stat().st_size > 0
    )


def result_payload(instrumental_path: Path, vocals_path: Path) -> dict[str, str | float]:
    duration = get_audio_duration(instrumental_path)
    return {
        "duration": duration,
        "instrumental_path": str(instrumental_path),
        "vocals_path": str(vocals_path),
    }


def convert_wav_to_mp3(wav_path: Path, output_path: Path | None = None) -> Path:
    """Convert a WAV file to MP3 for efficient and native Telegram audio delivery."""
    mp3_path = output_path or wav_path.with_suffix(".mp3")
    if mp3_path.exists() and mp3_path.stat().st_size > 0:
        return mp3_path

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(wav_path),
        "-c:a",
        "libmp3lame",
        "-b:a",
        "256k",
        str(mp3_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg MP3 conversion failed: {result.stderr}")
    return mp3_path




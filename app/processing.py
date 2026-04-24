import shutil
import subprocess
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


def separate_audio(
    input_path: Path,
    job_dir: Path,
    report_progress: ProgressCallback,
    separation_mode: str = "fast",
) -> dict[str, str | float]:
    input_dir = job_dir / "input"
    exports = job_dir / "exports"
    input_dir.mkdir(parents=True, exist_ok=True)
    exports.mkdir(parents=True, exist_ok=True)

    vocals_out = exports / "vocals.wav"
    instrumental_out = exports / "instrumental.wav"
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
    if separation_mode == "fast":
        run_fast_separator(audio_wav, job_dir, instrumental_out, vocals_out)
    else:
        run_demucs_separator(audio_wav, job_dir, instrumental_out, vocals_out)

    report_progress(90, "Saving stems")
    return result_payload(instrumental_out, vocals_out)


def outputs_are_ready(instrumental_path: Path, vocals_path: Path) -> bool:
    return (
        instrumental_path.exists()
        and vocals_path.exists()
        and instrumental_path.stat().st_size > 0
        and vocals_path.stat().st_size > 0
    )


def result_payload(instrumental_path: Path, vocals_path: Path) -> dict[str, str | float]:
    try:
        duration = float(sf.info(str(instrumental_path)).duration)
    except Exception:
        duration = 0.0

    return {
        "duration": duration,
        "instrumental_path": str(instrumental_path),
        "vocals_path": str(vocals_path),
    }


def run_demucs_separator(
    audio_wav: Path,
    job_dir: Path,
    instrumental_out: Path,
    vocals_out: Path,
) -> None:
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

    shutil.copy2(vocals, vocals_out)
    shutil.copy2(instrumental, instrumental_out)

    if not outputs_are_ready(instrumental_out, vocals_out):
        raise RuntimeError("Separated stems are empty")


def run_fast_separator(
    audio_wav: Path,
    job_dir: Path,
    instrumental_out: Path,
    vocals_out: Path,
) -> None:
    from audio_separator.separator import Separator

    fast_dir = job_dir / "uvr_fast"
    fast_dir.mkdir(parents=True, exist_ok=True)
    model_dir = config.FAST_SEPARATOR_MODEL_DIR
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        separator = Separator(
            output_dir=str(fast_dir),
            output_format="WAV",
            model_file_dir=str(model_dir),
            use_soundfile=True,
        )
    except TypeError:
        separator = Separator(
            output_dir=str(fast_dir),
            output_format="WAV",
            model_file_dir=str(model_dir),
        )
    separator.load_model(model_filename=config.FAST_SEPARATOR_MODEL)
    separated_files = separator.separate(str(audio_wav))
    separated_paths = [
        Path(path) if Path(path).is_absolute() else fast_dir / path
        for path in separated_files
    ]
    separated_paths.extend(fast_dir.glob("*.wav"))

    vocals = pick_stem(separated_paths, ["vocals", "vocal"])
    instrumental = pick_stem(
        separated_paths,
        ["instrumental", "no_vocals", "no-vocals", "inst"],
    )
    if not vocals or not instrumental:
        raise RuntimeError("Fast separator did not produce both stems")

    shutil.copy2(vocals, vocals_out)
    shutil.copy2(instrumental, instrumental_out)
    if not outputs_are_ready(instrumental_out, vocals_out):
        raise RuntimeError("Fast separator produced empty stems")


def pick_stem(paths: list[Path], tokens: list[str]) -> Path | None:
    seen: set[Path] = set()
    for path in paths:
        candidate = path
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        name = candidate.name.lower()
        if any(token in name for token in tokens):
            return candidate
    return None

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
    if config.FAST_SEPARATOR_BACKEND == "spleeter":
        run_spleeter_separator(audio_wav, instrumental_out, vocals_out)
        return

    if config.FAST_SEPARATOR_BACKEND == "uvr":
        run_uvr_separator(audio_wav, job_dir, instrumental_out, vocals_out)
        return

    run_sherpa_uvr_separator(audio_wav, instrumental_out, vocals_out)


def run_sherpa_uvr_separator(
    audio_wav: Path,
    instrumental_out: Path,
    vocals_out: Path,
) -> None:
    import numpy as np
    import sherpa_onnx

    model_path = ensure_sherpa_uvr_model()
    separator_config = sherpa_onnx.OfflineSourceSeparationConfig(
        model=sherpa_onnx.OfflineSourceSeparationModelConfig(
            uvr=sherpa_onnx.OfflineSourceSeparationUvrModelConfig(
                model=str(model_path),
            ),
            num_threads=max(1, config.FAST_SHERPA_UVR_NUM_THREADS),
            debug=False,
            provider="cpu",
        )
    )
    if not separator_config.validate():
        raise RuntimeError("Fast UVR separator model configuration is invalid")

    separator = sherpa_onnx.OfflineSourceSeparation(separator_config)
    samples, sample_rate = sf.read(str(audio_wav), dtype="float32", always_2d=True)
    samples = np.ascontiguousarray(samples.T)
    output = separator.process(sample_rate=sample_rate, samples=samples)
    if len(output.stems) != 2:
        raise RuntimeError("Fast UVR separator did not produce both stems")

    if config.FAST_SHERPA_UVR_TARGET_STEM == "instrumental":
        instrumental_stem = output.stems[0]
        vocals_stem = output.stems[1]
    else:
        vocals_stem = output.stems[0]
        instrumental_stem = output.stems[1]

    sf.write(
        str(vocals_out),
        vocals_stem.data.T,
        output.sample_rate,
        subtype="PCM_16",
    )
    sf.write(
        str(instrumental_out),
        instrumental_stem.data.T,
        output.sample_rate,
        subtype="PCM_16",
    )
    if not outputs_are_ready(instrumental_out, vocals_out):
        raise RuntimeError("Fast UVR separator produced empty stems")


def ensure_sherpa_uvr_model() -> Path:
    model_dir = config.FAST_SHERPA_UVR_MODEL_DIR
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / config.FAST_SHERPA_UVR_MODEL
    if model_path.exists() and model_path.stat().st_size > 0:
        return model_path

    temp_path = model_path.with_suffix(".tmp")
    url = f"{config.FAST_SHERPA_UVR_MODEL_URL_BASE}/{config.FAST_SHERPA_UVR_MODEL}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response, temp_path.open("wb") as out_file:
            shutil.copyfileobj(response, out_file)
        
        if not temp_path.exists() or temp_path.stat().st_size == 0:
            raise RuntimeError("Fast UVR separator model download is empty")
            
        temp_path.replace(model_path)
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Fast UVR separator model download failed: {exc}") from exc

    return model_path



def run_spleeter_separator(
    audio_wav: Path,
    instrumental_out: Path,
    vocals_out: Path,
) -> None:
    import numpy as np
    import sherpa_onnx

    model_dir = ensure_spleeter_model()
    vocals_model = model_dir / "vocals.fp16.onnx"
    accompaniment_model = model_dir / "accompaniment.fp16.onnx"
    separator_config = sherpa_onnx.OfflineSourceSeparationConfig(
        model=sherpa_onnx.OfflineSourceSeparationModelConfig(
            spleeter=sherpa_onnx.OfflineSourceSeparationSpleeterModelConfig(
                vocals=str(vocals_model),
                accompaniment=str(accompaniment_model),
            ),
            num_threads=max(1, config.FAST_SPLEETER_NUM_THREADS),
            debug=False,
            provider="cpu",
        )
    )
    if not separator_config.validate():
        raise RuntimeError("Fast separator model configuration is invalid")

    separator = sherpa_onnx.OfflineSourceSeparation(separator_config)
    samples, sample_rate = sf.read(str(audio_wav), dtype="float32", always_2d=True)
    samples = np.ascontiguousarray(samples.T)
    output = separator.process(sample_rate=sample_rate, samples=samples)
    if len(output.stems) != 2:
        raise RuntimeError("Fast separator did not produce both stems")

    sf.write(
        str(vocals_out),
        output.stems[0].data.T,
        output.sample_rate,
        subtype="PCM_16",
    )
    sf.write(
        str(instrumental_out),
        output.stems[1].data.T,
        output.sample_rate,
        subtype="PCM_16",
    )
    if not outputs_are_ready(instrumental_out, vocals_out):
        raise RuntimeError("Fast separator produced empty stems")


def ensure_spleeter_model() -> Path:
    root = config.FAST_SPLEETER_MODEL_DIR
    model_dir = root / "sherpa-onnx-spleeter-2stems-fp16"
    required = [model_dir / "vocals.fp16.onnx", model_dir / "accompaniment.fp16.onnx"]
    if all(path.exists() and path.stat().st_size > 0 for path in required):
        return model_dir

    root.mkdir(parents=True, exist_ok=True)
    archive = root / "sherpa-onnx-spleeter-2stems-fp16.tar.bz2"
    temp_archive = archive.with_suffix(".tmp")
    
    try:
        with urllib.request.urlopen(config.FAST_SPLEETER_MODEL_URL, timeout=30) as response, temp_archive.open("wb") as out_file:
            shutil.copyfileobj(response, out_file)
        
        if not temp_archive.exists() or temp_archive.stat().st_size == 0:
            raise RuntimeError("Spleeter model download is empty")
            
        temp_archive.replace(archive)
        
        temp_extract_dir = root / "spleeter_temp_extract"
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
        temp_extract_dir.mkdir(parents=True, exist_ok=True)
        
        with tarfile.open(archive, "r:bz2") as tar:
            safe_extract(tar, temp_extract_dir)
            
        extracted_folder = temp_extract_dir / "sherpa-onnx-spleeter-2stems-fp16"
        if not extracted_folder.exists():
            raise RuntimeError("Archive did not contain expected model directory")
            
        if model_dir.exists():
            shutil.rmtree(model_dir, ignore_errors=True)
        extracted_folder.rename(model_dir)
        shutil.rmtree(temp_extract_dir, ignore_errors=True)
    except Exception as exc:
        if temp_archive.exists():
            temp_archive.unlink(missing_ok=True)
        if archive.exists():
            archive.unlink(missing_ok=True)
        raise RuntimeError(f"Spleeter model preparation failed: {exc}") from exc
    finally:
        archive.unlink(missing_ok=True)

    if not all(path.exists() and path.stat().st_size > 0 for path in required):
        raise RuntimeError("Fast separator model download is incomplete")
    return model_dir



def safe_extract(tar: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in tar.getmembers():
        target = (destination / member.name).resolve()
        if target != destination and destination not in target.parents:
            raise RuntimeError(f"Unsafe model archive path: {member.name}")
    tar.extractall(destination)


def run_uvr_separator(
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

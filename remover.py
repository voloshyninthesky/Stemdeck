import os
import subprocess
from demucs.separate import main as demucs_separate
import logging
import shutil
import torchaudio

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_audio(input_file: str, output_audio: str):
    """Extract audio from MP4 to WAV using ffmpeg."""
    try:
        cmd = ["ffmpeg", "-i", input_file, "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", output_audio]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info(f"Extracted audio to {output_audio}")
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr.decode()}")
        raise Exception(f"Failed to extract audio: {e.stderr.decode()}")

def main():
    input_file = "file.mp4"
    temp_audio = "temp_audio.wav"
    output_dir = "output"
    instrumental_file = f"{output_dir}/htdemucs/temp_audio/no_vocals.wav"  # HDemucs output path

    try:
        # Check if input file exists
        if not os.path.exists(input_file):
            raise Exception(f"Input file {input_file} not found")

        # Create output directory
        os.makedirs(output_dir, exist_ok=True)

        # Extract audio from MP4
        extract_audio(input_file, temp_audio)

        # Check torchaudio backend
        backend = torchaudio.get_audio_backend()
        logger.info(f"Using torchaudio backend: {backend if backend else 'None'}")

        # Perform vocal separation with Hybrid Demucs
        logger.info("Starting vocal separation with Hybrid Demucs...")
        demucs_separate([
            "--two-stems", "vocals",
            "-o", output_dir,
            "-n", "htdemucs",  # Use Hybrid Demucs model
            "--device", "cpu",  # Explicitly use CPU
            temp_audio
        ])
        logger.info(f"Instrumental saved to {instrumental_file}")

        # Verify output
        if not os.path.exists(instrumental_file):
            raise Exception(f"Instrumental file not found at {instrumental_file}")

        # Rename output for clarity
        final_output = "instrumental.wav"
        os.rename(instrumental_file, final_output)
        logger.info(f"Final instrumental saved as {final_output}")

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise

    # finally:
    #     # Clean up temporary files
    #     if os.path.exists(temp_audio):
    #         os.remove(temp_audio)
    #     if os.path.exists(f"{output_dir}/htdemucs/temp_audio"):
    #         shutil.rmtree(f"{output_dir}/htdemucs/temp_audio", ignore_errors=True)
    #     if os.path.exists(f"{output_dir}/htdemucs") and not os.listdir(f"{output_dir}/htdemucs"):
    #         os.rmdir(f"{output_dir}/htdemucs")
    #     if os.path.exists(output_dir) and not os.listdir(output_dir):
    #         os.rmdir(output_dir)

if __name__ == "__main__":
    # Set torchaudio backend to ffmpeg
    os.environ["TORCHAUDIO_USE_BACKEND"] = "ffmpeg"
    main()
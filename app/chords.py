import librosa
import numpy as np
from pathlib import Path
from typing import Any

def detect_chords(audio_path: Path) -> list[dict[str, Any]]:
    """
    Detects chords from the given audio file using librosa's Chroma CENS features
    and template matching for 12 Major and 12 Minor chords.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Load audio. Resampling to 16000 Hz is plenty for chord recognition and runs fast.
    y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
    
    # Compute chroma features. Chroma CENS is smooth and ideal for chord matching.
    # hop_length=512 at sr=16000 gives 512/16000 = 0.032 seconds (32ms) per frame.
    chroma = librosa.feature.chroma_cens(y=y, sr=sr, hop_length=512)
    
    frames = chroma.shape[1]
    times = librosa.frames_to_time(np.arange(frames), sr=sr, hop_length=512)
    
    notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    
    # Define chord template families: suffix and semitone offsets from root
    chord_definitions = [
        ("", [0, 4, 7]),          # Major
        ("m", [0, 3, 7]),         # Minor
        ("7", [0, 4, 7, 10]),     # Dominant 7th
        ("maj7", [0, 4, 7, 11]),  # Major 7th
        ("m7", [0, 3, 7, 10]),    # Minor 7th
        ("sus4", [0, 5, 7]),      # Suspended 4th
        ("sus2", [0, 2, 7]),      # Suspended 2nd
        ("dim", [0, 3, 6]),       # Diminished
        ("aug", [0, 4, 8])        # Augmented
    ]
    
    templates = []
    chord_names = []
    
    for i in range(12):
        for suffix, offsets in chord_definitions:
            tpl = np.zeros(12)
            for offset in offsets:
                tpl[(i + offset) % 12] = 1.0
            tpl /= np.linalg.norm(tpl)
            templates.append(tpl)
            chord_names.append(notes[i] + suffix)
        
    templates = np.array(templates)  # shape: (108, 12)
    
    # Calculate similarities via dot product
    similarities = np.dot(templates, chroma)  # shape: (108, frames)
    
    # Choose the template index with highest similarity for each frame
    raw_matches = np.argmax(similarities, axis=0)
    
    # Smooth the matches using a rolling majority-vote filter.
    # A window size of 31 frames is ~1.0 second of audio.
    smoothed_matches = []
    window_size = 31
    half_w = window_size // 2
    for i in range(frames):
        start_idx = max(0, i - half_w)
        end_idx = min(frames, i + half_w + 1)
        counts = np.bincount(raw_matches[start_idx:end_idx])
        smoothed_matches.append(np.argmax(counts))
        
    # Group consecutive frames of the same chord into temporal segments
    segments = []
    current_chord = None
    current_start = 0.0
    
    for i, idx in enumerate(smoothed_matches):
        chord_name = chord_names[idx]
        t = times[i]
        
        if chord_name != current_chord:
            if current_chord is not None:
                segments.append({
                    "start": round(current_start, 2),
                    "end": round(t, 2),
                    "chord": current_chord
                })
            current_chord = chord_name
            current_start = t
            
    if current_chord is not None:
        segments.append({
            "start": round(current_start, 2),
            "end": round(float(times[-1]), 2),
            "chord": current_chord
        })
        
    # Post-processing: Merge very short segments (e.g. < 0.8 seconds) to prevent visual flickering.
    merged = []
    for seg in segments:
        if not merged:
            merged.append(seg)
        else:
            prev = merged[-1]
            if seg["chord"] == prev["chord"]:
                prev["end"] = seg["end"]
            elif (seg["end"] - seg["start"]) < 0.8:
                prev["end"] = seg["end"]
            else:
                merged.append(seg)
                
    return merged

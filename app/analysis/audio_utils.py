"""Audio preprocessing and validation using librosa."""

import logging
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000
# Young children often practise a single word ("snake"), which can run well under
# a second — especially after edge-silence trimming — so keep this gate low.
MIN_DURATION_SECONDS = 0.5
SILENCE_RMS_THRESHOLD = 0.005
TRIM_TOP_DB = 40  # trim leading/trailing audio quieter than this (dB below peak)
TARGET_LUFS = -20.0  # loudness-normalisation target (ITU-R BS.1770), per Zhang 2508.16681
PEAK_CEILING = 0.97  # leave headroom so normalisation never clips


def _normalize_loudness(y: np.ndarray, sr: int) -> np.ndarray:
    """Normalise to TARGET_LUFS so a quiet child and a loud one are scored on the
    same footing. Uses pyloudnorm (true BS.1770 loudness) when available, else an
    RMS-based approximation. Always peak-protected to avoid clipping.
    """
    if len(y) == 0:
        return y

    duration = len(y) / sr
    normalized: np.ndarray | None = None
    try:
        import pyloudnorm as pyln

        # pyloudnorm's gating block is 400 ms; shorter clips can't be measured.
        if duration >= 0.4:
            meter = pyln.Meter(sr)
            loudness = meter.integrated_loudness(y)
            if np.isfinite(loudness):
                normalized = pyln.normalize.loudness(y, loudness, TARGET_LUFS)
    except Exception:
        logger.info("pyloudnorm unavailable/failed; using RMS loudness fallback")

    if normalized is None:
        # RMS fallback: scale so 20*log10(rms) ≈ TARGET_LUFS (i.e. rms ≈ 0.1 at -20).
        rms = float(np.sqrt(np.mean(y**2)))
        if rms > 1e-6:
            target_rms = 10 ** (TARGET_LUFS / 20.0)
            normalized = y * (target_rms / rms)
        else:
            normalized = y

    # Peak-protect: scale down if normalisation pushed samples past the ceiling.
    peak = float(np.max(np.abs(normalized))) if len(normalized) else 0.0
    if peak > PEAK_CEILING:
        normalized = normalized * (PEAK_CEILING / peak)
    return normalized.astype(np.float32)


def preprocess_audio(input_path: str, output_path: str) -> str:
    """
    Load audio (mp3, wav, m4a, webm, etc.), resample to 16 kHz mono, trim edge
    silence, loudness-normalise, and save as WAV.

    Note: pre-emphasis is deliberately NOT applied here. It is applied only to the
    MFCC computation inside acoustic.py — applying it to this shared WAV would
    inflate high-frequency energy (breaking the fricative-vs-voiced discrimination
    in the acoustic layer) and needlessly alter the audio sent to Whisper.
    """
    input_path = str(input_path)
    output_path = str(output_path)

    y, sr = librosa.load(input_path, sr=TARGET_SAMPLE_RATE, mono=True)

    # Trim leading/trailing silence so dead air at the edges doesn't inflate
    # word durations or skew WPM. Interior silence (real blocks) is untouched.
    if len(y) > 0:
        trimmed, _ = librosa.effects.trim(y, top_db=TRIM_TOP_DB)
        if len(trimmed) > 0:
            y = trimmed

    # Loudness-normalise so absolute thresholds (e.g. the silence floor) and
    # cross-recording comparisons hold across quiet/loud children and mics.
    y = _normalize_loudness(y, TARGET_SAMPLE_RATE)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, y, TARGET_SAMPLE_RATE, subtype="PCM_16")

    logger.debug("Preprocessed audio saved to %s", output_path)
    return output_path


def get_audio_duration(audio_path: str) -> float:
    """Return audio duration in seconds."""
    duration = librosa.get_duration(path=audio_path)
    return float(duration)


def _rms_energy(audio_path: str) -> float:
    y, _ = librosa.load(audio_path, sr=TARGET_SAMPLE_RATE, mono=True)
    if len(y) == 0:
        return 0.0
    return float(np.sqrt(np.mean(y**2)))


def validate_audio(audio_path: str) -> bool:
    """
    Validate audio is long enough and not silent.
    Raises ValueError with a reason if invalid.
    """
    duration = get_audio_duration(audio_path)
    if duration < MIN_DURATION_SECONDS:
        raise ValueError(
            f"Audio too short: {duration:.2f}s (minimum {MIN_DURATION_SECONDS}s required)"
        )

    rms = _rms_energy(audio_path)
    if rms < SILENCE_RMS_THRESHOLD:
        raise ValueError("Audio appears silent or too quiet to process")

    return True

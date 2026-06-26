"""Acoustic-layer disfluency detection.

Analyses the audio waveform directly to find the *physical* signatures of
stuttering that a cleaned Whisper transcript erases:

  • Block            — a silent (or tense audible) stoppage mid-speech.
  • Prolongation     — a single sound held with an unchanging spectrum (voiced
                       vowel/nasal, or unvoiced fricative).
  • Sound repetition — rapid re-articulation of the same short sound ("b-b-ball").

This complements the text-based ``DisfluencyDetector``: Whisper tells us *what
words* were said; the acoustic layer tells us *how the sound actually behaved*.

Techniques adopted from Zhang, "Revisiting Rule-Based Stuttering Detection"
(arXiv:2508.16681):
  1. Speaking-rate normalisation of duration thresholds (T_min = α / syllable_rate)
     — fixed thresholds fail badly at off-nominal rates; children vary a lot.
  2. MFCC frame-to-frame correlation (> ~0.92) as the stationarity test for
     prolongation, instead of a fragile global-normalised spectral flux.
  3. F0 stability (Δf0 small) + harmonicity to validate *voiced* prolongations.
  4. DTW/MFCC-similarity of rapid onset bursts to detect sound repetitions.
  5. Audible (tense) block detection in addition to silent blocks.

All detectors stay deliberately conservative — a false positive in front of a
child is worse than a missed mild event. Thresholds are module-level constants so
they can be tuned against real recordings via scripts/evaluate.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import librosa
import numpy as np
from scipy.signal import find_peaks

logger = logging.getLogger(__name__)

SR = 16000
HOP = 256          # ~16 ms per frame at 16 kHz
FRAME = 512        # ~32 ms analysis window
EPS = 1e-8

# --- Energy thresholds (relative to the clip's own loud-vowel level) ----------
SILENCE_ABS = 0.008        # absolute RMS floor
SILENCE_FLOOR_REL = 0.05   # below this fraction of vowel energy = TRUE silence (block)
VOICE_REL = 0.18           # at/above this fraction = loud, vowel-level sound

# --- Duration thresholds (speaking-rate normalised: T = α / syllable_rate) -----
ALPHA_PROLONG = 1.2        # prolongation min-duration coefficient
ALPHA_BLOCK = 1.4          # block min-duration coefficient
PROLONG_MIN_BOUNDS = (0.25, 0.45)   # clamp normalised prolongation min (s); floor = Howell ~250ms
BLOCK_MIN_BOUNDS = (0.25, 0.40)     # clamp normalised block min (s)
MAX_BLOCK_S = 3.0          # silence longer than this is a recording gap, not a block
DEFAULT_SYLLABLE_RATE = 4.0
SYLLABLE_RATE_BOUNDS = (1.5, 7.0)

# --- Stationarity / character ------------------------------------------------
MFCC_CORR_STEADY = 0.92    # adjacent-frame MFCC correlation above this = "held"
FLUX_STEADY = 0.06         # fallback steadiness test if MFCC is unavailable
HF_CUTOFF_HZ = 3500.0      # band considered "high frequency"
HF_RATIO_FRIC = 0.45       # fraction of energy above cutoff that marks frication
ZCR_FRIC = 0.20            # zero-crossing rate above this is noise-like (fricative)

# --- F0 / harmonicity (voiced prolongation validation) -----------------------
USE_F0 = True              # pyin is the heaviest step; allow disabling for latency
F0_MIN_HZ = 100.0
F0_MAX_HZ = 500.0
F0_STABILITY_HZ = 15.0     # std of F0 across a voiced prolongation must be below this (paper θ_f0)
VOICED_PROB_MIN = 0.40     # mean voiced-probability proxy for harmonicity (HNR)

PRE_EMPHASIS = 0.97        # high-frequency pre-emphasis applied to the MFCC signal only

# --- Sound repetition --------------------------------------------------------
# EXPERIMENTAL: onset/MFCC-similarity based. Cannot be validated on synthetic
# audio (it over-fires on tonal signals) and carries a real false-positive risk,
# so it is OFF by default. Enable and CALIBRATE on real labelled child speech
# (scripts/evaluate.py against UCLASS / real clips) before turning on.
DETECT_SOUND_REPS = False
SOUNDREP_MAX_GAP_S = 0.30  # consecutive bursts closer than this may be a repeat
SOUNDREP_MIN_SIM = 0.80    # cosine similarity of burst MFCCs to count as "same sound"
SOUNDREP_WIN_S = 0.05      # half-window around an onset used to characterise the burst
SOUNDREP_MAX_SPAN_S = 1.2  # a repeat cluster longer than this is normal speech, not a stutter

# --- Audible (tense) block ---------------------------------------------------
# EXPERIMENTAL: tense-phonation blocks are easily confused with quiet voicing.
# OFF by default; enable and calibrate on real labelled child speech first.
DETECT_AUDIBLE_BLOCKS = False

# Merge tolerance: bridge dropouts up to this many frames so a single held sound
# whose energy momentarily dips is not split into two events.
BRIDGE_FRAMES = 2          # ~32 ms


@dataclass
class AcousticFeatures:
  """Frame-level acoustic features, computed once per clip."""

  y: np.ndarray
  sr: int
  rms: np.ndarray            # per-frame energy
  flux: np.ndarray           # per-frame normalised spectral flux (fallback steadiness)
  mfcc_corr: np.ndarray      # adjacent-frame MFCC correlation (primary steadiness)
  hf_ratio: np.ndarray       # fraction of energy above HF_CUTOFF_HZ
  zcr: np.ndarray            # zero-crossing rate (noise-like-ness)
  f0: np.ndarray             # fundamental frequency (Hz), NaN where unvoiced
  voiced_prob: np.ndarray    # harmonicity proxy in [0,1]
  mfcc: np.ndarray           # (n_mfcc, T) for burst-similarity comparisons
  times: np.ndarray          # frame start times in seconds
  hop: int
  speech_threshold: float    # vowel-level energy threshold (loud speech)
  silence_floor: float       # true-silence energy floor (below this = a block)
  syllable_rate: float       # estimated syllables/sec
  prolong_min_s: float       # rate-normalised prolongation min duration
  block_min_s: float         # rate-normalised block min duration

  @property
  def frame_dur(self) -> float:
    return self.hop / self.sr if self.sr else 0.0

  @property
  def duration(self) -> float:
    return len(self.y) / self.sr if self.sr else 0.0


def _adjacent_mfcc_correlation(mfcc: np.ndarray) -> np.ndarray:
  """Pearson correlation between consecutive MFCC frames (energy coeff dropped).

  ~1.0 = the spectral shape is unchanging (a held sound); lower = the spectrum is
  moving (normal speech). More robust than energy-scaled spectral flux.
  """
  if mfcc.shape[1] < 2:
    return np.zeros(mfcc.shape[1])
  m = mfcc[1:]                                   # drop the 0th (energy) coefficient
  m = m - m.mean(axis=0, keepdims=True)          # centre each frame across coeffs
  norm = np.linalg.norm(m, axis=0)
  dots = np.sum(m[:, 1:] * m[:, :-1], axis=0)
  denom = norm[1:] * norm[:-1] + EPS
  corr = dots / denom
  return np.concatenate([[0.0], corr])           # first frame has no predecessor


def _estimate_syllable_rate(rms: np.ndarray, frame_dur: float, speech_threshold: float) -> float:
  """Estimate syllables/sec by counting energy-envelope peaks (syllable nuclei)."""
  voiced = rms >= speech_threshold
  speech_dur = float(voiced.sum()) * frame_dur
  if speech_dur < 0.3 or not voiced.any():
    return DEFAULT_SYLLABLE_RATE
  k = max(1, int(round(0.08 / frame_dur)))       # ~80 ms smoothing
  env = np.convolve(rms, np.ones(k) / k, mode="same")
  height = max(speech_threshold, 0.5 * float(np.median(env[voiced])))
  distance = max(1, int(round(0.12 / frame_dur)))  # syllables >= ~120 ms apart
  peaks, _ = find_peaks(env, height=height, distance=distance)
  if len(peaks) == 0:
    return DEFAULT_SYLLABLE_RATE
  rate = len(peaks) / speech_dur
  return float(np.clip(rate, *SYLLABLE_RATE_BOUNDS))


def analyze_audio(wav_path: str) -> AcousticFeatures | None:
  """Load a WAV and compute frame-level features used by every detector."""
  try:
    y, sr = librosa.load(wav_path, sr=SR, mono=True)
  except Exception:
    logger.warning("acoustic: failed to load %s", wav_path)
    return None

  if y is None or len(y) == 0:
    return None

  rms = librosa.feature.rms(y=y, frame_length=FRAME, hop_length=HOP)[0]
  times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP)

  spectrum = np.abs(librosa.stft(y, n_fft=FRAME, hop_length=HOP))

  # Spectral flux (fallback steadiness measure).
  diff = np.diff(spectrum, axis=1)
  diff[diff < 0] = 0.0
  flux = np.sqrt(np.sum(diff**2, axis=0))
  flux = np.concatenate([[0.0], flux])
  if flux.max() > EPS:
    flux = flux / flux.max()

  # High-frequency energy ratio: fricative (high) vs vowel (low) vs silence (none).
  freqs = librosa.fft_frequencies(sr=sr, n_fft=FRAME)
  hf_mask = freqs >= HF_CUTOFF_HZ
  total_energy = spectrum.sum(axis=0) + EPS
  hf_ratio = spectrum[hf_mask].sum(axis=0) / total_energy

  zcr = librosa.feature.zero_crossing_rate(y, frame_length=FRAME, hop_length=HOP)[0]

  # MFCCs + adjacent-frame correlation (primary stationarity test). Pre-emphasis
  # is applied HERE only (not to the shared WAV): it flattens spectral tilt, which
  # is standard for MFCCs and sharpens the stationarity measure.
  y_pre = np.append(y[0], y[1:] - PRE_EMPHASIS * y[:-1])
  mfcc = librosa.feature.mfcc(y=y_pre, sr=sr, n_mfcc=13, n_fft=FRAME, hop_length=HOP)
  mfcc_corr = _adjacent_mfcc_correlation(mfcc)

  # F0 + harmonicity (voiced-prolongation validation). Heaviest step; guarded.
  if USE_F0:
    try:
      f0, _, voiced_prob = librosa.pyin(
        y, fmin=F0_MIN_HZ, fmax=F0_MAX_HZ, sr=sr, frame_length=1024, hop_length=HOP
      )
      voiced_prob = np.nan_to_num(voiced_prob, nan=0.0)
    except Exception:
      logger.info("acoustic: pyin failed; skipping F0 validation")
      f0 = np.full(len(rms), np.nan)
      voiced_prob = np.zeros(len(rms))
  else:
    f0 = np.full(len(rms), np.nan)
    voiced_prob = np.zeros(len(rms))

  n = min(len(rms), len(flux), len(mfcc_corr), len(hf_ratio), len(zcr),
          len(f0), len(voiced_prob), mfcc.shape[1], len(times))
  if n == 0:
    return None
  rms, flux, mfcc_corr = rms[:n], flux[:n], mfcc_corr[:n]
  hf_ratio, zcr = hf_ratio[:n], zcr[:n]
  f0, voiced_prob = f0[:n], voiced_prob[:n]
  mfcc, times = mfcc[:, :n], times[:n]

  speech_level = float(np.percentile(rms, 90))
  speech_threshold = max(SILENCE_ABS, VOICE_REL * speech_level)
  silence_floor = max(SILENCE_ABS, SILENCE_FLOOR_REL * speech_level)

  frame_dur = HOP / sr
  syllable_rate = _estimate_syllable_rate(rms, frame_dur, speech_threshold)
  prolong_min_s = float(np.clip(ALPHA_PROLONG / syllable_rate, *PROLONG_MIN_BOUNDS))
  block_min_s = float(np.clip(ALPHA_BLOCK / syllable_rate, *BLOCK_MIN_BOUNDS))

  return AcousticFeatures(
    y=y, sr=sr, rms=rms, flux=flux, mfcc_corr=mfcc_corr, hf_ratio=hf_ratio, zcr=zcr,
    f0=f0, voiced_prob=voiced_prob, mfcc=mfcc, times=times, hop=HOP,
    speech_threshold=speech_threshold, silence_floor=silence_floor,
    syllable_rate=syllable_rate, prolong_min_s=prolong_min_s, block_min_s=block_min_s,
  )


def _runs(mask: np.ndarray, bridge: int = 0) -> list[tuple[int, int]]:
  """Return (start, end_inclusive) index pairs for runs of True, bridging gaps
  of at most ``bridge`` False frames so a momentary dip doesn't split a run."""
  runs: list[tuple[int, int]] = []
  i, n = 0, len(mask)
  while i < n:
    if mask[i]:
      j = i
      while j + 1 < n and mask[j + 1]:
        j += 1
      runs.append((i, j))
      i = j + 1
    else:
      i += 1

  if bridge <= 0 or len(runs) < 2:
    return runs
  merged = [runs[0]]
  for start, end in runs[1:]:
    ps, pe = merged[-1]
    if start - pe - 1 <= bridge:
      merged[-1] = (ps, end)
    else:
      merged.append((start, end))
  return merged


def _severity_from_duration(dur: float, moderate: float, severe: float) -> str:
  if dur >= severe:
    return "severe"
  if dur >= moderate:
    return "moderate"
  return "mild"


def _steady_mask(features: AcousticFeatures) -> np.ndarray:
  """Frames whose spectrum is unchanging.

  Requires BOTH a high adjacent-frame MFCC correlation (spectral *shape* held)
  AND low spectral flux (spectral *magnitude* held). Combining them is stricter
  and more robust than either alone — MFCC correlation catches held shape, flux
  rejects signals whose shape is similar but whose energy is still moving.
  """
  flux_steady = features.flux < FLUX_STEADY
  if np.any(features.mfcc_corr):
    return (features.mfcc_corr >= MFCC_CORR_STEADY) & flux_steady
  return flux_steady


def detect_blocks(features: AcousticFeatures) -> list[dict[str, Any]]:
  """Silent blocks (true silence) and, optionally, audible tense blocks."""
  rms, times = features.rms, features.times
  if len(rms) < 3:
    return []

  silent = rms < features.silence_floor
  speech = ~silent
  if not speech.any():
    return []

  first_speech = int(np.argmax(speech))
  last_speech = len(speech) - 1 - int(np.argmax(speech[::-1]))
  frame_dur = features.frame_dur
  block_min = features.block_min_s
  results: list[dict[str, Any]] = []

  def _interior(start: int, end: int) -> bool:
    return start > first_speech and end < last_speech

  # Silent blocks: interior runs of true silence.
  for start, end in _runs(silent):
    if not _interior(start, end):
      continue
    dur = (end - start + 1) * frame_dur
    if dur < block_min:
      continue
    if dur > MAX_BLOCK_S:
      logger.info("acoustic: ignoring %.2fs silence as recording gap (> %.1fs)", dur, MAX_BLOCK_S)
      continue
    results.append({
      "type": "block", "character": "silent",
      "timestamp_start": round(float(times[start]), 3),
      "timestamp_end": round(float(times[end]), 3),
      "pause_duration": round(float(dur), 3),
      "severity": _severity_from_duration(dur, moderate=0.5, severe=1.0),
      "source": "acoustic",
      "evidence": {
        "syllable_rate": round(features.syllable_rate, 2),
        "normalized_duration_syllables": round(float(dur * features.syllable_rate), 2),
        "min_duration_s": round(block_min, 3),
      },
    })

  # Audible (tense) blocks: sustained low-amplitude, low-high-freq, steady,
  # weakly-voiced energy — laryngeal tension rather than clean voicing or frication.
  if DETECT_AUDIBLE_BLOCKS:
    steady = _steady_mask(features)
    audible_tense = (
      (rms >= features.silence_floor) & (rms < features.speech_threshold)
      & steady
      & (features.hf_ratio < HF_RATIO_FRIC)
      & (features.voiced_prob < VOICED_PROB_MIN)
    )
    for start, end in _runs(audible_tense, bridge=BRIDGE_FRAMES):
      if not _interior(start, end):
        continue
      dur = (end - start + 1) * frame_dur
      if dur < block_min or dur > MAX_BLOCK_S:
        continue
      results.append({
        "type": "block", "character": "audible",
        "timestamp_start": round(float(times[start]), 3),
        "timestamp_end": round(float(times[end]), 3),
        "pause_duration": round(float(dur), 3),
        "severity": _severity_from_duration(dur, moderate=0.5, severe=1.0),
        "source": "acoustic",
        "evidence": {
          "syllable_rate": round(features.syllable_rate, 2),
          "normalized_duration_syllables": round(float(dur * features.syllable_rate), 2),
          "min_duration_s": round(block_min, 3),
          "mean_hf_ratio": round(float(np.mean(features.hf_ratio[start:end + 1])), 3),
        },
      })
  return results


def detect_prolongations(features: AcousticFeatures) -> list[dict[str, Any]]:
  """Held sounds: voiced (vowel/nasal) or unvoiced fricative, with a steady spectrum."""
  rms = features.rms
  if len(rms) < 3:
    return []

  audible = rms >= features.silence_floor
  voiced_loud = rms >= features.speech_threshold
  steady = _steady_mask(features)

  voiced_held = voiced_loud & steady
  fricative_held = audible & (features.hf_ratio >= HF_RATIO_FRIC) & (features.zcr >= ZCR_FRIC)
  held = voiced_held | fricative_held

  frame_dur = features.frame_dur
  prolong_min = features.prolong_min_s
  results: list[dict[str, Any]] = []

  for start, end in _runs(held, bridge=BRIDGE_FRAMES):
    dur = (end - start + 1) * frame_dur
    if dur < prolong_min:
      continue
    seg = slice(start, end + 1)
    is_fricative = bool(np.mean(features.hf_ratio[seg]) >= HF_RATIO_FRIC)

    # Acoustic evidence behind the decision (interpretability — paper's core value).
    evidence: dict[str, Any] = {
      "mfcc_corr": round(float(np.mean(features.mfcc_corr[seg])), 3),
      "syllable_rate": round(features.syllable_rate, 2),
      "normalized_duration_syllables": round(float(dur * features.syllable_rate), 2),
      "min_duration_s": round(features.prolong_min_s, 3),
    }

    if is_fricative:
      evidence["hf_ratio"] = round(float(np.mean(features.hf_ratio[seg])), 3)
      evidence["zcr"] = round(float(np.mean(features.zcr[seg])), 3)
    else:
      f0_seg = features.f0[seg]
      f0_valid = f0_seg[~np.isnan(f0_seg)]
      f0_std = float(np.std(f0_valid)) if f0_valid.size else None
      hnr_proxy = float(np.mean(features.voiced_prob[seg]))
      evidence["f0_std_hz"] = round(f0_std, 1) if f0_std is not None else None
      evidence["hnr_proxy"] = round(hnr_proxy, 3)
      if USE_F0:
        # Validate a VOICED prolongation with pitch stability + harmonicity, which
        # rejects spurious "held" runs that are not actually a sustained voiced sound.
        stable_f0 = f0_valid.size >= 3 and f0_std is not None and f0_std <= F0_STABILITY_HZ
        if not (stable_f0 and hnr_proxy >= VOICED_PROB_MIN):
          continue

    results.append({
      "type": "prolongation",
      "timestamp_start": round(float(features.times[start]), 3),
      "timestamp_end": round(float(features.times[end]), 3),
      "actual_duration": round(float(dur), 3),
      "character": "fricative" if is_fricative else "voiced",
      "severity": _severity_from_duration(dur, moderate=0.55, severe=1.0),
      "source": "acoustic",
      "evidence": evidence,
    })
  return results


def _onset_burst_vectors(features: AcousticFeatures, onset_frames: np.ndarray) -> list[np.ndarray]:
  """Average MFCC (shape coeffs only) in a small window around each onset."""
  half = max(1, int(round(SOUNDREP_WIN_S / features.frame_dur)))
  vecs: list[np.ndarray] = []
  for fr in onset_frames:
    lo = max(0, fr - half)
    hi = min(features.mfcc.shape[1], fr + half + 1)
    vecs.append(features.mfcc[1:, lo:hi].mean(axis=1))
  return vecs


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
  na, nb = np.linalg.norm(a), np.linalg.norm(b)
  if na < EPS or nb < EPS:
    return 0.0
  return float(np.dot(a, b) / (na * nb))


def detect_sound_repetitions(features: AcousticFeatures) -> list[dict[str, Any]]:
  """Detect rapid re-articulation of the same short sound ("b-b-ball").

  Find onset bursts, then cluster consecutive bursts that are (a) close in time
  and (b) acoustically similar (high MFCC cosine similarity). A cluster of >= 2
  such bursts within a short span is a sound repetition. This is the rule-based
  alternative to a learned model for this category.
  """
  if features.mfcc.shape[1] < 4:
    return []
  try:
    onset_frames = librosa.onset.onset_detect(
      y=features.y, sr=features.sr, hop_length=features.hop, backtrack=True
    )
  except Exception:
    return []
  if len(onset_frames) < 2:
    return []

  onset_frames = np.asarray([f for f in onset_frames if f < features.mfcc.shape[1]])
  if len(onset_frames) < 2:
    return []
  onset_times = features.times[onset_frames]
  vecs = _onset_burst_vectors(features, onset_frames)
  frame_dur = features.frame_dur

  results: list[dict[str, Any]] = []
  i = 0
  n = len(onset_frames)
  while i < n - 1:
    cluster = [i]
    j = i
    while (
      j + 1 < n
      and (onset_times[j + 1] - onset_times[j]) <= SOUNDREP_MAX_GAP_S
      and _cosine(vecs[j], vecs[j + 1]) >= SOUNDREP_MIN_SIM
    ):
      cluster.append(j + 1)
      j += 1

    if len(cluster) >= 2:
      start_t = float(onset_times[cluster[0]])
      end_t = float(onset_times[cluster[-1]]) + SOUNDREP_WIN_S
      span = end_t - start_t
      if span <= SOUNDREP_MAX_SPAN_S:
        extra = len(cluster) - 1
        severity = "severe" if extra >= 3 else "moderate" if extra >= 2 else "mild"
        results.append({
          "type": "repetition", "character": "sound",
          "timestamp_start": round(start_t, 3),
          "timestamp_end": round(end_t, 3),
          "repeat_count": len(cluster),
          "severity": severity,
          "source": "acoustic",
        })
      i = j + 1
    else:
      i += 1
  return results


def detect_all_acoustic(features: AcousticFeatures | None) -> list[dict[str, Any]]:
  """Run every acoustic detector and return a combined, time-sorted list."""
  if features is None:
    return []
  results = detect_blocks(features) + detect_prolongations(features)
  if DETECT_SOUND_REPS:
    results += detect_sound_repetitions(features)
  results.sort(key=lambda d: d.get("timestamp_start", 0.0))
  return results


def debug_frames(wav_path: str) -> dict[str, Any]:
  """Dump frame-level features + derived thresholds for tuning against real audio."""
  f = analyze_audio(wav_path)
  if f is None:
    return {}
  return {
    "speech_threshold": f.speech_threshold,
    "silence_floor": f.silence_floor,
    "syllable_rate": f.syllable_rate,
    "prolong_min_s": f.prolong_min_s,
    "block_min_s": f.block_min_s,
    "frame_dur": f.frame_dur,
    "times": f.times.tolist(),
    "rms": f.rms.tolist(),
    "mfcc_corr": f.mfcc_corr.tolist(),
    "hf_ratio": f.hf_ratio.tolist(),
    "zcr": f.zcr.tolist(),
    "f0": np.nan_to_num(f.f0, nan=0.0).tolist(),
    "voiced_prob": f.voiced_prob.tolist(),
  }

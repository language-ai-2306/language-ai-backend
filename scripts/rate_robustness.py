"""Speaking-rate robustness test (reproduces Zhang 2508.16681, Table 3).

Time-stretches every eval clip across a range of speaking rates and checks that
detections stay stable. Compares the rate-NORMALISED thresholds (current code)
against FIXED thresholds (the pre-paper approach) to demonstrate that
normalisation prevents the collapse fixed thresholds suffer at extreme rates.

This is the one experiment that VALIDATES the speaking-rate normalisation without
any real labelled data — it perturbs the rate of clips whose content we know.

Usage:
    .venv/bin/python -m scripts.rate_robustness
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis.acoustic import (  # noqa: E402
  analyze_audio, detect_blocks, detect_prolongations,
)

LABELS_PATH = ROOT / "data" / "eval" / "labels.jsonl"
RATES = [0.5, 0.75, 1.0, 1.5, 2.0]
SR = 16000

# The fixed thresholds the system used before rate normalisation (the baseline we
# are arguing against). 0.30 s for both prolongation and block.
FIXED_PROLONG_S = 0.30
FIXED_BLOCK_S = 0.30


def _load_clips(path: Path) -> list[dict]:
  clips = []
  with open(path) as f:
    for line in f:
      line = line.strip()
      if line and not line.startswith("#"):
        clips.append(json.loads(line))
  return clips


def _detect_types(wav_path: str, fixed: bool) -> set[str]:
  """Return the set of disfluency types detected in a clip. If ``fixed``, override
  the rate-normalised duration thresholds with the old fixed ones."""
  f = analyze_audio(wav_path)
  if f is None:
    return set()
  if fixed:
    f.prolong_min_s = FIXED_PROLONG_S
    f.block_min_s = FIXED_BLOCK_S
  dets = detect_blocks(f) + detect_prolongations(f)
  return {d["type"] for d in dets}


def main() -> int:
  if not LABELS_PATH.exists():
    print("No labels.jsonl — run: .venv/bin/python -m scripts.make_synthetic_eval")
    return 1
  clips = _load_clips(LABELS_PATH)

  # Pre-load each clip's audio once.
  loaded = []
  for c in clips:
    y, _ = librosa.load(str((ROOT / c["audio_path"]).resolve()), sr=SR, mono=True)
    expected = {lbl["type"] for lbl in c.get("labels", [])}
    loaded.append((c["clip_id"], y, expected, c.get("is_fluent", not expected)))

  # results[mode][rate] = {"recall_hits","recall_total","fp_hits","fp_total"}
  results = {m: {r: {"rh": 0, "rt": 0, "fh": 0, "ft": 0} for r in RATES}
             for m in ("normalized", "fixed")}

  with tempfile.TemporaryDirectory() as tmp:
    for clip_id, y, expected, is_fluent in loaded:
      for rate in RATES:
        ys = y if rate == 1.0 else librosa.effects.time_stretch(y, rate=rate)
        wav = str(Path(tmp) / f"{clip_id}_{rate}.wav")
        sf.write(wav, ys, SR)
        for mode in ("normalized", "fixed"):
          detected = _detect_types(wav, fixed=(mode == "fixed"))
          cell = results[mode][rate]
          if is_fluent:
            cell["ft"] += 1
            if detected:
              cell["fh"] += 1
          else:
            for t in expected:
              cell["rt"] += 1
              if t in detected:
                cell["rh"] += 1

  def _pct(h: int, t: int) -> str:
    return f"{(h / t * 100):5.0f}%" if t else "   n/a"

  print(f"\nSpeaking-rate robustness  ({len(clips)} clips, rates {RATES})\n")
  print("Recall on disfluent clips (higher = better):")
  print(f"  {'rate':>8}" + "".join(f"{r:>8}" for r in RATES))
  for mode in ("normalized", "fixed"):
    row = "".join(_pct(results[mode][r]["rh"], results[mode][r]["rt"]) + " " for r in RATES)
    print(f"  {mode:>8}  {row}")

  print("\nFalse positives on fluent clips (lower = better):")
  print(f"  {'rate':>8}" + "".join(f"{r:>8}" for r in RATES))
  for mode in ("normalized", "fixed"):
    row = "".join(_pct(results[mode][r]["fh"], results[mode][r]["ft"]) + " " for r in RATES)
    print(f"  {mode:>8}  {row}")

  # Headline: average recall across all rates, normalized vs fixed.
  def _avg_recall(mode: str) -> float:
    h = sum(results[mode][r]["rh"] for r in RATES)
    t = sum(results[mode][r]["rt"] for r in RATES)
    return h / t if t else 0.0

  print(f"\nAvg recall across all rates — normalized: {_avg_recall('normalized'):.0%}"
        f"  vs  fixed: {_avg_recall('fixed'):.0%}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())

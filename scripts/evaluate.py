"""Evaluate the analysis pipeline against the labelled ground-truth set.

Runs ``pipeline.analyze`` over every clip in ``data/eval/labels.jsonl`` and
compares the predicted disfluencies to the gold labels, reporting:

  • per-type precision / recall / F1 (temporal-tolerance matching),
  • false-positive rate on fluent clips (the metric that matters most), and
  • severity agreement on the matched events.

This is the measurement tool that unblocks threshold calibration and regression
testing. A change to acoustic.py / scorer.py is "good" only if the numbers here
improve (or at least hold) — especially the fluent-clip FP rate.

Usage:
    .venv/bin/python -m scripts.evaluate [--use-ml] [--tolerance 0.25] [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis import pipeline  # noqa: E402
from app.services.ml_service import MLServiceError, ml_service  # noqa: E402

LABELS_PATH = ROOT / "data" / "eval" / "labels.jsonl"
TYPES = ["block", "prolongation", "repetition", "interjection", "revision"]
SEVERITIES = ["mild", "moderate", "severe"]


def _load_clips(path: Path) -> list[dict[str, Any]]:
  clips: list[dict[str, Any]] = []
  with open(path) as f:
    for line in f:
      line = line.strip()
      if line and not line.startswith("#"):
        clips.append(json.loads(line))
  return clips


def _resolve_words(clip: dict[str, Any], use_ml: bool) -> tuple[str, list[dict[str, Any]]]:
  """Get transcript + words: cached in the clip, else via ML, else a mock."""
  if clip.get("words") is not None:
    return clip.get("transcript", ""), clip["words"]

  reference = clip.get("reference_phrase", "")
  if use_ml:
    wav_path = str((ROOT / clip["audio_path"]).resolve())
    with open(wav_path, "rb") as fh:
      wav_bytes = fh.read()
    try:
      t = asyncio.run(ml_service.transcribe(wav_bytes, filename="clip.wav"))
      return t["transcript"], t["words"]
    except MLServiceError:
      print(f"  ! ML unavailable for {clip['clip_id']}; using mock transcript")

  mock = ml_service.mock_transcribe(reference)
  return mock["transcript"], mock["words"]


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
  lo = max(a["start"], b["start"])
  hi = min(a["end"], b["end"])
  return max(0.0, hi - lo)


def _close(p: dict[str, Any], g: dict[str, Any], tol: float) -> bool:
  """A prediction matches a label if they overlap, or their midpoints are within
  ``tol`` seconds (handles point-like blocks and small boundary drift)."""
  if _overlap(p, g) > 0:
    return True
  pm = (p["start"] + p["end"]) / 2
  gm = (g["start"] + g["end"]) / 2
  return abs(pm - gm) <= tol


def _norm_pred(d: dict[str, Any]) -> dict[str, Any]:
  return {
    "type": d.get("type"),
    "start": float(d.get("timestamp_start", 0.0)),
    "end": float(d.get("timestamp_end", 0.0)),
    "severity": d.get("severity", "mild"),
  }


def _match(
  preds: list[dict[str, Any]], golds: list[dict[str, Any]], tol: float
) -> tuple[list[tuple], list[dict], list[dict]]:
  """Greedy best-overlap matching, per type. Returns (tp_pairs, fp, fn)."""
  used: set[int] = set()
  tp: list[tuple] = []
  fp: list[dict] = []
  for p in preds:
    best_i, best_ov = None, -1.0
    for i, g in enumerate(golds):
      if i in used or g["type"] != p["type"] or not _close(p, g, tol):
        continue
      ov = _overlap(p, g)
      if ov > best_ov:
        best_i, best_ov = i, ov
    if best_i is not None:
      used.add(best_i)
      tp.append((p, golds[best_i]))
    else:
      fp.append(p)
  fn = [g for i, g in enumerate(golds) if i not in used]
  return tp, fp, fn


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
  precision = tp / (tp + fp) if (tp + fp) else 0.0
  recall = tp / (tp + fn) if (tp + fn) else 0.0
  f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
  return precision, recall, f1


def evaluate(clips: list[dict[str, Any]], use_ml: bool, tol: float) -> dict[str, Any]:
  counts = {t: {"tp": 0, "fp": 0, "fn": 0} for t in TYPES}
  sev_conf: dict[tuple[str, str], int] = {}
  fluent_total = 0
  fluent_false_alarms = 0
  per_clip: list[dict[str, Any]] = []

  for clip in clips:
    transcript, words = _resolve_words(clip, use_ml)
    wav_path = str((ROOT / clip["audio_path"]).resolve())
    result = pipeline.analyze(
      wav_path, transcript, words, clip.get("reference_phrase", ""), clip.get("child_age", 8)
    )
    preds = [_norm_pred(d) for d in result["disfluencies"]]
    golds = [dict(g) for g in clip.get("labels", [])]

    tp, fp, fn = _match(preds, golds, tol)
    for t in TYPES:
      counts[t]["tp"] += sum(1 for _, g in tp if g["type"] == t)
      counts[t]["fp"] += sum(1 for p in fp if p["type"] == t)
      counts[t]["fn"] += sum(1 for g in fn if g["type"] == t)
    for p, g in tp:
      key = (g["severity"], p["severity"])
      sev_conf[key] = sev_conf.get(key, 0) + 1

    is_fluent = clip.get("is_fluent", len(golds) == 0)
    if is_fluent:
      fluent_total += 1
      if preds:
        fluent_false_alarms += 1

    per_clip.append({
      "clip_id": clip["clip_id"],
      "audio_path": clip.get("audio_path"),
      "child_age": clip.get("child_age", 8),
      "reference_phrase": clip.get("reference_phrase", ""),
      "transcript": transcript,
      "words": words,
      "tp": len(tp), "fp": len(fp), "fn": len(fn),
      "predicted": preds, "gold": golds,
    })

  sev_matched = sum(sev_conf.values())
  sev_agree = sum(v for (g, p), v in sev_conf.items() if g == p)
  total = {k: sum(counts[t][k] for t in TYPES) for k in ("tp", "fp", "fn")}

  return {
    "n_clips": len(clips),
    "per_type": {t: {**counts[t], "prf": _prf(**counts[t])} for t in TYPES},
    "overall": {**total, "prf": _prf(**total)},
    "fluent": {
      "clips": fluent_total,
      "false_alarms": fluent_false_alarms,
      "fp_rate": fluent_false_alarms / fluent_total if fluent_total else 0.0,
    },
    "severity": {
      "matched": sev_matched,
      "agreement": sev_agree / sev_matched if sev_matched else 0.0,
      "confusion": {f"{g}->{p}": v for (g, p), v in sorted(sev_conf.items())},
    },
    "per_clip": per_clip,
  }


def _print_report(rep: dict[str, Any]) -> None:
  print(f"\nEvaluated {rep['n_clips']} clip(s)\n")
  print(f"{'type':<14}{'P':>7}{'R':>7}{'F1':>7}{'TP':>5}{'FP':>5}{'FN':>5}")
  print("-" * 50)
  for t, m in rep["per_type"].items():
    p, r, f1 = m["prf"]
    if m["tp"] or m["fp"] or m["fn"]:
      print(f"{t:<14}{p:>7.2f}{r:>7.2f}{f1:>7.2f}{m['tp']:>5}{m['fp']:>5}{m['fn']:>5}")
  p, r, f1 = rep["overall"]["prf"]
  o = rep["overall"]
  print("-" * 50)
  print(f"{'OVERALL':<14}{p:>7.2f}{r:>7.2f}{f1:>7.2f}{o['tp']:>5}{o['fp']:>5}{o['fn']:>5}")

  fl = rep["fluent"]
  print(f"\nFluent-clip false-positive rate: {fl['fp_rate']:.1%} "
        f"({fl['false_alarms']}/{fl['clips']} fluent clips falsely flagged)")

  sv = rep["severity"]
  print(f"Severity agreement (on matched events): {sv['agreement']:.1%} "
        f"({sv['matched']} matched)")
  if sv["confusion"]:
    print("  confusion (gold->pred):", sv["confusion"])

  fails = [c for c in rep["per_clip"] if c["fp"] or c["fn"]]
  if fails:
    print(f"\nClips with errors ({len(fails)}):")
    for c in fails:
      print(f"  {c['clip_id']}: TP={c['tp']} FP={c['fp']} FN={c['fn']}")


def _dump_predictions(rep: dict[str, Any], path: str) -> None:
  """Write the model's predictions in the label schema so an annotator can CORRECT
  them instead of labelling from scratch (active learning). Review every line —
  these are model guesses, not ground truth."""
  with open(path, "w") as f:
    for c in rep["per_clip"]:
      record = {
        "clip_id": c["clip_id"],
        "audio_path": c["audio_path"],
        "child_age": c["child_age"],
        "reference_phrase": c["reference_phrase"],
        "transcript": c["transcript"],
        "words": c["words"],
        "is_fluent": len(c["predicted"]) == 0,
        "labels": [
          {"type": p["type"], "start": p["start"], "end": p["end"], "severity": p["severity"]}
          for p in c["predicted"]
        ],
        "annotator": "MODEL_PREDICTION_NEEDS_REVIEW",
      }
      f.write(json.dumps(record) + "\n")
  print(f"\nWrote {len(rep['per_clip'])} prediction stubs to {path} — REVIEW before use.")


def main() -> int:
  ap = argparse.ArgumentParser(description="Evaluate the analysis pipeline.")
  ap.add_argument("--labels", default=str(LABELS_PATH), help="path to labels.jsonl")
  ap.add_argument("--use-ml", action="store_true", help="transcribe via the ML service")
  ap.add_argument("--tolerance", type=float, default=0.25, help="temporal match window (s)")
  ap.add_argument("--json", default=None, help="write the full report to this JSON file")
  ap.add_argument("--dump-predictions", default=None,
                  help="write model predictions in the label schema (for SLP correction)")
  ap.add_argument("--fail-under", type=float, default=None,
                  help="exit non-zero if overall F1 is below this (regression gate)")
  ap.add_argument("--max-fp-rate", type=float, default=None,
                  help="exit non-zero if the fluent-clip false-positive rate exceeds this")
  args = ap.parse_args()

  path = Path(args.labels)
  if not path.exists():
    print(f"No labels file at {path}. Generate the seed set:\n"
          f"  .venv/bin/python -m scripts.make_synthetic_eval")
    return 1

  clips = _load_clips(path)
  if not clips:
    print("No clips found in labels file.")
    return 1

  rep = evaluate(clips, use_ml=args.use_ml, tol=args.tolerance)
  _print_report(rep)
  if args.json:
    with open(args.json, "w") as f:
      json.dump(rep, f, indent=2)
    print(f"\nWrote report to {args.json}")
  if args.dump_predictions:
    _dump_predictions(rep, args.dump_predictions)

  # Regression gate: non-zero exit fails CI.
  exit_code = 0
  f1 = rep["overall"]["prf"][2]
  fp_rate = rep["fluent"]["fp_rate"]
  if args.fail_under is not None and f1 < args.fail_under:
    print(f"\nFAIL: overall F1 {f1:.3f} < --fail-under {args.fail_under}")
    exit_code = 1
  if args.max_fp_rate is not None and fp_rate > args.max_fp_rate:
    print(f"FAIL: fluent FP rate {fp_rate:.1%} > --max-fp-rate {args.max_fp_rate:.1%}")
    exit_code = 1
  if exit_code == 0 and (args.fail_under is not None or args.max_fp_rate is not None):
    print("\nPASS: regression gate satisfied")
  return exit_code


if __name__ == "__main__":
  raise SystemExit(main())

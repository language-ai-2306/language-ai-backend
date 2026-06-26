# Manual testing guide — disfluency analysis

How to manually test the speech-analysis pipeline (`app/analysis/`) end-to-end,
what to expect for each case, and where to get real child recordings. Pair this
with the automated harness (`scripts/evaluate.py`) — this doc is for hands-on,
real-audio checks; the harness is for regression numbers.

> **Most important acceptance criterion:** the system must **not** flag a fluent
> child. A false positive in front of a child is the worst failure mode. Spend at
> least half your testing on fluent (control) clips.

---

## 1. How to run one manual test

Both services must be up: ML/transcription on **:8081**, backend on **:8000**
(see the run commands in the repo root). Then:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/audio/analyze \
  -F 'audio=@clip.wav' \
  -F 'reference_phrase=I see a snake' \
  -F 'child_age=8' | python3 -m json.tool
```

Add `-F 'use_mock=true'` to bypass the ML service (mock transcript) when you only
want to exercise the acoustic layer.

### What to read in the output

| Field | What it tells you |
|-------|-------------------|
| `disfluencies[]` | each detected event: `type`, `character`, `timestamp_start/end`, `severity`, `evidence` |
| `disfluencies[].evidence` | **why** it fired — `mfcc_corr`, `syllable_rate`, `normalized_duration_syllables`, `hnr_proxy`/`f0_std_hz` or `hf_ratio`/`zcr` |
| `recognition.dominant_disfluency` | the single most impactful type |
| `recognition.stress_words` / `stress_sounds` | which word/sound the child got stuck on |
| `scores.fluency_score` | 0–100; drops with more/severe disfluencies |
| `scores.stutter_frequency_percent` | % of words carrying a core stutter |
| `scores.avg_pause_duration` | mean **block** duration (0 if no blocks) |
| `feedback[]` | kid-facing coaching messages |

---

## 2. Where to get test recordings

### A. Real stuttering datasets (best — real disfluencies, annotated)

| Dataset | Population | Contents / labels | Access |
|---------|-----------|-------------------|--------|
| **UCLASS** (UCL Archive of Stuttered Speech) | **Children + adults** (60 children) | Recordings with event-level annotations; the closest match to our population | Free for research, register at UCL |
| **FluencyBank** (TalkBank) | Adults + **some children** | CHAT-format transcripts, clinical annotations | Mostly open; some password-gated |
| **SEP-28k** (Apple) | Adults (podcasts) | 28k×3s clips, per-type labels | Free on GitHub; you download the source audio |

### B. Fluent children's speech (for the control / false-positive half)

You need clean, *non*-stuttered child speech to prove the system stays quiet.

| Corpus | Population | Notes |
|--------|-----------|-------|
| **OGI Kids' Speech Corpus** (CSLU) | Children K–grade 10 | Read + spontaneous; great age coverage |
| **MyST – My Science Tutor** | Grades 3–5 | Large spontaneous conversational set |
| **CMU Kids Corpus** (LDC) | Children | Read sentences (LDC license) |
| **PF-STAR** | British children | Read children's speech |
| **Mozilla Common Voice** | Mixed (some kids) | Free; age labels unreliable — filter carefully |

### C. Record your own (fastest to start, fully in your control)

1. Get **written parental consent** (these are minors — see §6).
2. Record on a phone in a quiet room; export WAV/m4a.
3. Have the child read/say the reference phrase; for disfluent test clips, have
   an adult **deliberately produce** the target disfluency (see §3) since it's
   hard to elicit real stutters on demand.
4. Preprocess to the canonical 16 kHz mono WAV (so timestamps line up):
   ```bash
   .venv/bin/python -c "from app.analysis.audio_utils import preprocess_audio as p; p('raw.m4a','clip.wav')"
   ```
5. For ground truth, an SLP (or you) annotates per `data/eval/README.md`.

> **Ethics caution:** do **not** scrape stuttering videos from YouTube/social
> media for a product test set — consent and child-privacy issues. One-off
> smoke tests with adult self-produced disfluencies are fine.

### D. Synthetic clips (already in the repo)

`python -m scripts.make_synthetic_eval` regenerates controlled clips in
`data/eval/synthetic/`. Good for the energy/fricative path; **cannot** validate
the MFCC/F0/syllable-rate features (they need real speech) — see §5.

---

## 3. Manual test matrix — by disfluency type

For each, the "produce" column is how to make the test clip (adult demo is fine).
Run with the matching `reference_phrase` and the child's `child_age`.

| # | Type | Produce | Expected detection | Expected dominant | Notes |
|---|------|---------|--------------------|-------------------|-------|
| T1 | **Fluent (control)** | Say the phrase cleanly | **No disfluencies** | `null` | High fluency (~95–100), FP=0. **The key test.** |
| T2 | **Fricative prolongation** | "sssssnake", "fffish" | 1 `prolongation`, `character: fricative`, sound = onset | `prolongation` | `evidence.hf_ratio` high, `zcr` high |
| T3 | **Voiced prolongation** | "mmmmom", "gooo" (held vowel) | 1 `prolongation`, `character: voiced` | `prolongation` | `evidence.f0_std_hz` low, `hnr_proxy` ≥0.4 |
| T4 | **Silent block** | Pause 0.4–1s *inside* a word before releasing | 1 `block`, `character: silent` | `block` | `avg_pause_duration` > 0 |
| T5 | **Word repetition** | "I-I-I see", "the the dog" | `repetition` (text layer) | `repetition` | needs real/mock transcript with the repeat |
| T6 | **Interjection** | "um", "uh" inserted | `interjection` | (low impact) | fillers only |
| T7 | **Revision** | Start over: "I want—I see a snake" | `revision` | (context) | restart/insertion |
| T8 | **Sound repetition** | "b-b-ball", "k-k-cat" | **NOT detected (currently)** | — | `DETECT_SOUND_REPS=False` until real-data calibration — *expected gap* |
| T9 | **Audible/tense block** | Strained "[tense]…ball" | **NOT detected (currently)** | — | `DETECT_AUDIBLE_BLOCKS=False` — *expected gap* |
| T10 | **Mixed** | "sss-snake" then pause | prolongation **and** block, conflict-resolved | per precedence | events ≥100 ms apart |

---

## 4. Age-band scenarios (5–15) with expected cases

Use age-appropriate phrases. The pipeline is age-aware mainly in **feedback tone**
and the **summary**; detection itself is the same. Set `child_age` correctly.

### Ages 5–7 (single words / very short phrases)

| Phrase | Produce | Expected |
|--------|---------|----------|
| `snake` | clean | no disfluency; warm, simple summary ("Wow, amazing job!") |
| `snake` | "sssssnake" | fricative prolongation on `snake`, sound `s`; gentle feedback |
| `ball` | "b…(block)…ball" | silent block before `ball` |
| `mommy` | "mmmommy" | voiced prolongation |
| `I see a snake` | clean | no disfluency, fluency ~95–100 |
| `go` | "gooo" (held) | voiced prolongation; single-word clip accepted (≥0.5 s) |

### Ages 8–11 (short sentences)

| Phrase | Produce | Expected |
|--------|---------|----------|
| `I want to play outside` | clean | no disfluency; summary mentions the fluency score |
| `I want to play outside` | "I-I want" | word repetition on `I` |
| `The dog ran fast` | "ffffast" | fricative prolongation on `fast` |
| `The dog ran fast` | pause before `dog` | silent block; `avg_pause_duration` > 0 |
| `Can I have some water` | "um, can I…" | interjection (`um`), low impact, not dominant |

### Ages 12–15 (longer / complex sentences)

| Phrase | Produce | Expected |
|--------|---------|----------|
| `Yesterday I went to the store` | clean | no disfluency; mature summary (fluency/clarity/confidence) |
| `Yesterday I went to the store` | "y…(block)…yesterday" | block at the start, dominant `block` |
| `My favorite subject is science` | "sssscience" | fricative prolongation on `science` |
| `I think we should go now` | "I think we—I think we should" | revision |
| `She sells seashells` (tongue-twister) | clean, fast | **no disfluency** even at speed (rate-normalization) — *but see §5* |

---

## 5. Robustness / edge-case tests

| # | Test | How | Expected |
|---|------|-----|----------|
| R1 | **Quiet vs loud child** | Record same phrase very soft, then loud | Same detection result (loudness-normalized to −20 LUFS) |
| R2 | **Fast speaker** | Say phrase quickly, fluently | No false prolongation (rate-normalized thresholds) |
| R3 | **Slow speaker** | Say phrase slowly, fluently, with natural pauses | No false block/prolongation; natural pauses are not flagged |
| R4 | **Background noise** | Add room/TV noise | Acknowledged weakness — may degrade; note any false positives |
| R5 | **Very short clip** (<0.5 s) | One quick word | Rejected: "Audio too short" (validation) |
| R6 | **Silent/empty clip** | Silence only | Rejected: "Audio appears silent or too quiet" |
| R7 | **ML service down** | Stop :8081, run a real session | **503** "temporarily unavailable" — no fake scores saved |
| R8 | **Long recording gap** | 4 s of silence mid-clip | Gap ignored (not a block; > `MAX_BLOCK_S` = 3 s) |

> **R2/R3 caveat:** the rate-normalization machinery is in place, but the
> syllable-rate estimator is only reliable on **real syllabic speech** — it can't
> be validated on synthetic tones. These two tests are exactly where real child
> recordings matter most.

---

## 6. Acceptance criteria & known expected gaps

**Pass bar (qualitative, until you have a labeled set):**
- **0 false positives** across all fluent (T1, R1–R3, age-band "clean") clips.
- Each deliberate disfluency (T2–T7) detected with the right `type`/`character`.
- `evidence` present and sensible on every acoustic detection.
- ML-down returns 503, never fabricated scores.

**Expected gaps (these are NOT bugs right now):**
- **Sound repetition** ("b-b-ball", T8) — not detected; detector is gated OFF
  pending real-data calibration.
- **Audible/tense blocks** (T9) — not detected; gated OFF.
- **Phoneme-level "which exact sound"** — approximate for non-fricatives.
- Severity may be off by one band on borderline-duration events (needs
  calibration on real clips).

**Ethics for any real child audio:** written parental consent, secure storage,
defined retention, and SLP review of both labels and the feedback messages before
anything is shown to a child.

---

## 7. Quick checklist

```
[ ] Fluent single word (age 6)         -> no disfluency
[ ] Fluent sentence (age 10)           -> no disfluency
[ ] Fluent complex sentence (age 14)   -> no disfluency
[ ] Fricative prolongation "sssnake"   -> prolongation/fricative
[ ] Voiced prolongation "mmmom"        -> prolongation/voiced
[ ] Silent block                       -> block, avg_pause>0
[ ] Word repetition "I-I"              -> repetition
[ ] Interjection "um"                  -> interjection (not dominant)
[ ] Revision / restart                 -> revision
[ ] Quiet vs loud (same phrase)        -> same result
[ ] Fast fluent speech                 -> no false prolongation
[ ] Slow fluent speech w/ pauses       -> no false block
[ ] <0.5s clip                         -> rejected (too short)
[ ] ML service down                    -> 503, no saved scores
[ ] Sound rep "b-b-ball"               -> NOT detected (expected gap)
```

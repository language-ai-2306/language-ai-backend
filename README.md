# language-ai-backend

Voice-first speech companion backend for children aged 5–14 who stutter. Handles audio ingestion, session management, therapist plan management, disfluency analysis, and orchestration of the ML pipeline.

## Tech stack

- Python + FastAPI
- librosa / numpy / scipy / pyloudnorm (audio DSP)
- httpx (ML service client)

## Project structure

```
app/
├── main.py                        # FastAPI app, mounts router, /health
├── api/
│   └── audio.py                   # POST /v1/audio/analyze, GET /v1/audio/defaults
├── analysis/
│   ├── pipeline.py                # orchestrator — entry point for analysis
│   ├── acoustic.py                # block + prolongation from waveform
│   ├── detector.py                # repetition / interjection / revision from text
│   ├── recognition.py             # merge acoustic + text, resolve conflicts
│   ├── scorer.py                  # fluency score, WPM, stutter frequency
│   ├── feedback.py                # kid-friendly coaching messages
│   ├── audio_utils.py             # resample, trim, loudness-normalise
│   └── text_utils.py              # text normalisation helpers
├── services/
│   └── ml_client.py               # HTTP client for the ML transcription service
└── config/
    └── settings.py                # reads ML_SERVICE_URL from .env
scripts/
├── try_recognition.py             # CLI: run analysis on a local file
├── evaluate.py                    # offline F1 / FP-rate evaluation harness
├── make_synthetic_eval.py         # generate synthetic test clips
└── rate_robustness.py             # time-stretch speaking-rate test
docs/
└── manual_testing.md              # manual test guide with age-band scenarios
```

## Prerequisites

- Python 3.12+
- ML service running on `:8081` (optional for local dev — pass `use_mock=true`)

## Setup

1. Clone and enter the repo:

```bash
cd language-ai-backend
```

2. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Configure environment variables:

```bash
cp .env.example .env
```

Update `ML_SERVICE_URL` in `.env` (default `http://127.0.0.1:8081`).

4. Start the API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On startup, phrases are seeded from `data/phrases/` if the table is empty.

## Docker

```bash
docker build -t language-ai-backend .
docker run --env-file .env -p 8000:8000 language-ai-backend
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{status, service}`. |
| GET | `/v1/audio/defaults` | Shows current ML service URL and default values. |
| POST | `/v1/audio/analyze` | Full disfluency analysis. Multipart: `audio` (any format), `reference_phrase`, `child_age` (5–14), `use_mock` (bool — skips ML service). |

## Speech analysis (app/analysis/)

All disfluency analysis runs **in this backend**, under `app/analysis/` — rule/DSP logic, not an ML model:

- `acoustic.py` — block + prolongation detection from the waveform (librosa, loudness-normalised)
- `detector.py` — lexical disfluencies: repetition / interjection / revision
- `recognition.py` — fuses text + acoustic, resolves conflicts, picks the dominant disfluency and stress words/sounds
- `scorer.py` — fluency score, WPM, stutter frequency, avg pause duration
- `feedback.py` — kid-friendly coaching messages
- `audio_utils.py` — preprocessing: resample → trim silence → normalise to −20 LUFS
- `pipeline.py` — orchestrator: WAV + transcript → full result dict

Quick test without a database:

```bash
# requires ML service on :8081, or add -F 'use_mock=true' to skip it
curl -s -X POST http://127.0.0.1:8000/v1/audio/analyze \
  -F 'audio=@recording.wav' \
  -F 'reference_phrase=I see a snake' \
  -F 'child_age=8' | python3 -m json.tool

# or from the CLI:
.venv/bin/python -m scripts.try_recognition recording.wav "I see a snake" 8
```

## ML (transcription) integration

The only ML model is Whisper, in the separate `language-ai-ml` service (`:8081`). The backend preprocesses audio to a 16 kHz WAV and calls:

```
POST {ML_SERVICE_URL}/v1/transcribe   (multipart: audio=<wav>)
→ { "transcript": "...", "words": [{word, start, end, confidence}] }
```

The backend then runs `app/analysis/` on the same WAV. If the ML service is unavailable the request returns **HTTP 503** — no fake scores are saved.

## Privacy

Child records are referenced by UUID only in logs. Do not log names or other PII in production.

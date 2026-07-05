# Prompt-DJ

An AI that mixes music like a DJ from plain-language prompts. Upload two songs;
get a DJ-style mix of Song 1's beat + Song 2's vocals; steer it live with words.
"Claude Code for DJing."

See [docs/functional-spec.md](docs/functional-spec.md) for what it does and
[docs/implementation-plan.md](docs/implementation-plan.md) for how far along it is.

## Status

**M1 (upload skeleton) complete.** Upload two songs → each is cleaned to a
standard 44.1 kHz stereo WAV → play both back. Next: M2 (analysis + stems).

## Requirements

- Python 3.11, FFmpeg (on PATH), Node 20+.

## Run it (two terminals)

**1. Backend** (the audio engine + API):

```bash
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt      # macOS/Linux
.venv/Scripts/python -m uvicorn app.main:app --port 8000  # Windows
# .venv/bin/python -m uvicorn app.main:app --port 8000      # macOS/Linux
```

**2. Front end** (the web page):

```bash
npm install          # once, from the repo root
npm run dev          # opens http://localhost:5173
```

Open http://localhost:5173, drop two songs, click **Process**, and play both back.

## Tests

```bash
# Backend (from services/api)
.venv/Scripts/python -m pytest        # Windows

# Front end (from repo root)
npm test
npm run typecheck
npm run lint
```

## Layout

```
apps/web/       React + Vite + TypeScript — the web page
services/api/   Python + FastAPI — receives, cleans (FFmpeg), stores, serves audio
docs/           living specs (functional, technical, implementation plan) + reference
data/           cleaned audio (gitignored)
```

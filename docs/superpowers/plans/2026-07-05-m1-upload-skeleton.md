# M1 Upload Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A web page where a user drops two songs, clicks Process, and within seconds plays back both songs cleaned to a standard format (44.1kHz stereo WAV) and volume (peak-normalized).

**Architecture:** React (Vite) front end calls a FastAPI back end over one synchronous multipart request. The back end validates each file, cleans it with FFmpeg, stores it on local disk under a content-hash name, and serves it back by id. No database or job queue in M1.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, python-multipart, pytest, httpx (TestClient), FFmpeg (subprocess). React 18 + Vite + TypeScript, Vitest + Testing Library.

## Global Constraints

- Python 3.11; Node 20+ (dev machine has Node 24).
- FFmpeg invoked via `subprocess` (already on PATH); no GPL-licensed audio libs linked.
- Allowed upload types: `.mp3 .wav .m4a .flac .ogg` (MIME `audio/*`); hard size cap **30 MB per file**.
- Uploaded filenames are NEVER used as stored paths — store under a computed content hash; keep the original name only as a display label.
- Cleaned audio target: **44100 Hz, 2 channels, 16-bit PCM WAV, peak-normalized to 0 dBFS**.
- Audio/user data lives in `data/` (gitignored); never committed.
- Dangerous-path files (`services/api/app/routes/songs.py`, `app/storage.py`, `app/config.py`) require the confirm-and-apply flow when edited.

---

### Task 1: Backend scaffold + config + health check

**Files:**
- Create: `services/api/requirements.txt`, `services/api/app/__init__.py`, `services/api/app/config.py`, `services/api/app/main.py`, `services/api/tests/__init__.py`, `services/api/tests/test_health.py`, `services/api/pytest.ini`

**Interfaces:**
- Produces: `app.config.Settings` with `data_dir: Path`, `max_file_bytes: int = 30*1024*1024`, `allowed_exts: set[str]`, `allowed_cors_origins: list[str]`; singleton `settings`. `app.main.app` (FastAPI) with `GET /health` → `{"status": "ok"}`.

- [ ] **Step 1: Write requirements.txt**
```
fastapi==0.115.*
uvicorn[standard]==0.32.*
python-multipart==0.0.*
pytest==8.*
httpx==0.27.*
```

- [ ] **Step 2: Write the failing test** — `services/api/tests/test_health.py`
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 3: Run it, verify it fails** — `cd services/api && python -m pytest tests/test_health.py -v` → FAIL (import error).

- [ ] **Step 4: Write `app/config.py`**
```python
from pathlib import Path
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    max_file_bytes: int = 30 * 1024 * 1024
    allowed_exts: frozenset[str] = frozenset({".mp3", ".wav", ".m4a", ".flac", ".ogg"})
    allowed_cors_origins: tuple[str, ...] = ("http://localhost:5173",)

settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 5: Write `app/main.py` + `app/__init__.py` (empty) + `pytest.ini`**
```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings

app = FastAPI(title="Prompt-DJ API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_cors_origins),
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}
```
```ini
# pytest.ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 6: Run test, verify pass** → `python -m pytest tests/test_health.py -v` → PASS.

- [ ] **Step 7: Commit** — `git add services/api && git commit -m "feat(api): backend scaffold, config, health check"`

---

### Task 2: Audio normalize (FFmpeg wrapper)

**Files:**
- Create: `services/api/app/audio/__init__.py`, `services/api/app/audio/normalize.py`, `services/api/tests/test_normalize.py`

**Interfaces:**
- Produces: `normalize_audio(src: Path, dst: Path) -> None` — decodes `src`, writes a 44.1kHz/2ch/16-bit peak-normalized WAV to `dst`; raises `AudioError` on failure. Also `class AudioError(Exception)`.

- [ ] **Step 1: Write the failing test** — `tests/test_normalize.py`
```python
import subprocess, wave
from pathlib import Path
import pytest
from app.audio.normalize import normalize_audio, AudioError

def _make_tone(path: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-ac", "1", "-ar", "22050", str(path)],
        check=True, capture_output=True,
    )

def test_normalize_produces_standard_wav(tmp_path):
    src = tmp_path / "in.wav"; dst = tmp_path / "out.wav"
    _make_tone(src)
    normalize_audio(src, dst)
    with wave.open(str(dst), "rb") as w:
        assert w.getframerate() == 44100
        assert w.getnchannels() == 2
        assert w.getsampwidth() == 2  # 16-bit

def test_normalize_rejects_garbage(tmp_path):
    src = tmp_path / "bad.wav"; dst = tmp_path / "out.wav"
    src.write_bytes(b"not audio at all")
    with pytest.raises(AudioError):
        normalize_audio(src, dst)
```

- [ ] **Step 2: Run, verify fail** → `python -m pytest tests/test_normalize.py -v` → FAIL (import).

- [ ] **Step 3: Implement `app/audio/normalize.py`** (two-pass peak normalize)
```python
import re, subprocess
from pathlib import Path

class AudioError(Exception):
    pass

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)

def _measure_peak_db(src: Path) -> float:
    # Pass 1: detect the current peak so we can lift it to 0 dBFS.
    p = _run(["ffmpeg", "-i", str(src), "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", p.stderr)
    if p.returncode != 0 or m is None:
        raise AudioError(f"could not analyze audio: {p.stderr[-300:]}")
    return float(m.group(1))

def normalize_audio(src: Path, dst: Path) -> None:
    peak_db = _measure_peak_db(src)
    gain = -peak_db  # bring peak to 0 dBFS
    # Pass 2: apply gain + standardize to 44.1k / stereo / 16-bit PCM WAV.
    p = _run([
        "ffmpeg", "-y", "-i", str(src),
        "-af", f"volume={gain}dB",
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
        str(dst),
    ])
    if p.returncode != 0 or not dst.exists():
        raise AudioError(f"could not normalize audio: {p.stderr[-300:]}")
```

- [ ] **Step 4: Run, verify pass** → `python -m pytest tests/test_normalize.py -v` → PASS.

- [ ] **Step 5: Commit** — `git add services/api && git commit -m "feat(api): FFmpeg normalize to 44.1k stereo peak-normalized WAV"`

---

### Task 3: Content-hash storage

**Files:**
- Create: `services/api/app/storage.py`, `services/api/tests/test_storage.py`  *(dangerous-path: `storage.py`)*

**Interfaces:**
- Produces: `store_wav(wav_path: Path) -> str` (copies into `data/`, returns hex content-id); `path_for(song_id: str) -> Path | None` (returns stored path or None if missing/invalid id).

- [ ] **Step 1: Write the failing test** — `tests/test_storage.py`
```python
import wave, subprocess
from pathlib import Path
from app.storage import store_wav, path_for

def _wav(path: Path):
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i","sine=frequency=440:duration=1",
                    "-ar","44100","-ac","2","-c:a","pcm_s16le",str(path)],
                   check=True, capture_output=True)

def test_store_and_retrieve(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage.settings, "data_dir", tmp_path, raising=False)
    src = tmp_path / "clean.wav"; _wav(src)
    sid = store_wav(src)
    assert sid and path_for(sid) is not None and path_for(sid).exists()

def test_unknown_or_bad_id_returns_none(tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage.settings, "data_dir", tmp_path, raising=False)
    assert path_for("../etc/passwd") is None
    assert path_for("deadbeef") is None
```

- [ ] **Step 2: Run, verify fail** → FAIL (import).

- [ ] **Step 3: Implement `app/storage.py`**
```python
import hashlib, shutil, re
from pathlib import Path
from app.config import settings

_HEX = re.compile(r"^[0-9a-f]{64}$")

def store_wav(wav_path: Path) -> str:
    data = wav_path.read_bytes()
    sid = hashlib.sha256(data).hexdigest()
    dst = settings.data_dir / f"{sid}.wav"
    if not dst.exists():
        shutil.copyfile(wav_path, dst)
    return sid

def path_for(song_id: str) -> Path | None:
    if not _HEX.match(song_id):   # reject traversal / malformed ids
        return None
    p = settings.data_dir / f"{song_id}.wav"
    return p if p.exists() else None
```

- [ ] **Step 4: Run, verify pass** → PASS.

- [ ] **Step 5: Commit** — `git add services/api && git commit -m "feat(api): content-hash storage with id validation"`

---

### Task 4: Song model + upload/serve routes (the dangerous surface)

**Files:**
- Create: `services/api/app/models.py`, `services/api/app/routes/__init__.py`, `services/api/app/routes/songs.py`, `services/api/tests/test_songs_route.py`
- Modify: `services/api/app/main.py` (include the router)  *(dangerous-path: `routes/songs.py`)*

**Interfaces:**
- Consumes: `normalize_audio`, `AudioError` (Task 2); `store_wav`, `path_for` (Task 3); `settings` (Task 1).
- Produces: `POST /songs` (multipart fields `song1`, `song2`) → `{"songs": [Song, Song]}`; `GET /songs/{song_id}/audio` → WAV bytes. `Song = {id, original_name, url, status}`.

- [ ] **Step 1: Write the failing test** — `tests/test_songs_route.py`
```python
import io, subprocess
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def _bytes(tmp_path: Path, name: str) -> bytes:
    p = tmp_path / name
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i","sine=frequency=330:duration=1",
                    "-ar","22050","-ac","1",str(p)], check=True, capture_output=True)
    return p.read_bytes()

def test_upload_two_songs_ok(tmp_path):
    a = _bytes(tmp_path, "a.wav"); b = _bytes(tmp_path, "b.wav")
    r = client.post("/songs", files={
        "song1": ("a.wav", io.BytesIO(a), "audio/wav"),
        "song2": ("b.wav", io.BytesIO(b), "audio/wav"),
    })
    assert r.status_code == 200
    songs = r.json()["songs"]
    assert len(songs) == 2 and all(s["id"] and s["url"] for s in songs)
    audio = client.get(songs[0]["url"])
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"

def test_reject_non_audio(tmp_path):
    r = client.post("/songs", files={
        "song1": ("x.txt", io.BytesIO(b"hello"), "text/plain"),
        "song2": ("y.txt", io.BytesIO(b"hello"), "text/plain"),
    })
    assert r.status_code == 400

def test_unknown_audio_id_404():
    assert client.get("/songs/deadbeef/audio").status_code == 404
```

- [ ] **Step 2: Run, verify fail** → FAIL.

- [ ] **Step 3: Implement `app/models.py`**
```python
from pydantic import BaseModel

class Song(BaseModel):
    id: str
    original_name: str
    url: str
    status: str = "ready"
```

- [ ] **Step 4: Implement `app/routes/songs.py`**
```python
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, HTTPException
from fastapi.responses import FileResponse
from app.config import settings
from app.audio.normalize import normalize_audio, AudioError
from app.storage import store_wav, path_for
from app.models import Song

router = APIRouter()

def _validate(f: UploadFile) -> None:
    ext = Path(f.filename or "").suffix.lower()
    if ext not in settings.allowed_exts:
        raise HTTPException(400, f"'{f.filename}' is not a supported audio file.")

def _process(f: UploadFile) -> Song:
    _validate(f)
    raw = f.file.read()
    if len(raw) > settings.max_file_bytes:
        raise HTTPException(400, f"'{f.filename}' is larger than 30 MB.")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in"; src.write_bytes(raw)
        out = Path(td) / "out.wav"
        try:
            normalize_audio(src, out)
        except AudioError:
            raise HTTPException(400, f"Could not read '{f.filename}' as audio.")
        sid = store_wav(out)
    return Song(id=sid, original_name=f.filename or "song", url=f"/songs/{sid}/audio")

@router.post("/songs")
def upload_songs(song1: UploadFile, song2: UploadFile):
    return {"songs": [_process(song1), _process(song2)]}

@router.get("/songs/{song_id}/audio")
def get_audio(song_id: str):
    p = path_for(song_id)
    if p is None:
        raise HTTPException(404, "Song not found.")
    return FileResponse(p, media_type="audio/wav")
```

- [ ] **Step 5: Wire router in `app/main.py`** — add:
```python
from app.routes.songs import router as songs_router
app.include_router(songs_router)
```

- [ ] **Step 6: Run tests, verify pass** → `python -m pytest -v` → all PASS.

- [ ] **Step 7: Commit** — `git add services/api && git commit -m "feat(api): upload two songs + serve audio (validated)"`

---

### Task 5: Frontend scaffold + API client

**Files:**
- Create: `package.json` (root, workspaces), `apps/web/package.json`, `apps/web/vite.config.ts`, `apps/web/tsconfig.json`, `apps/web/index.html`, `apps/web/src/main.tsx`, `apps/web/src/App.tsx`, `apps/web/src/lib/api.ts`, `apps/web/.eslintrc.cjs`, `apps/web/vitest.config.ts`, `apps/web/src/lib/api.test.ts`

**Interfaces:**
- Produces: `uploadSongs(file1: File, file2: File): Promise<{songs: SongDTO[]}>` where `SongDTO = {id, original_name, url, status}`; `API_BASE` constant. Root npm scripts: `typecheck`, `lint`, `test`, `coverage`, `format`.

- [ ] **Step 1: Root `package.json`**
```json
{
  "name": "prompt-dj",
  "private": true,
  "workspaces": ["apps/web"],
  "scripts": {
    "typecheck": "npm -w apps/web run typecheck",
    "lint": "npm -w apps/web run lint",
    "test": "npm -w apps/web run test",
    "coverage": "npm -w apps/web run coverage",
    "format": "npm -w apps/web run format"
  }
}
```

- [ ] **Step 2: `apps/web/package.json`** (React 18, Vite 5, TS, Vitest, Testing Library, eslint, prettier). Scripts: `dev`, `build`, `typecheck: "tsc --noEmit"`, `lint: "eslint src"`, `test: "vitest run"`, `coverage: "vitest run --coverage --coverage.reporter=json-summary"`, `format: "prettier -w src"`.

- [ ] **Step 3: `apps/web/src/lib/api.ts`**
```ts
export const API_BASE = "http://localhost:8000";

export type SongDTO = { id: string; original_name: string; url: string; status: string };

export async function uploadSongs(file1: File, file2: File): Promise<{ songs: SongDTO[] }> {
  const body = new FormData();
  body.append("song1", file1);
  body.append("song2", file2);
  const res = await fetch(`${API_BASE}/songs`, { method: "POST", body });
  if (!res.ok) {
    const msg = await res.json().catch(() => ({ detail: "Upload failed." }));
    throw new Error(msg.detail ?? "Upload failed.");
  }
  return res.json();
}
```

- [ ] **Step 4: Write `src/lib/api.test.ts`** — mock `fetch`; assert `uploadSongs` posts FormData and returns parsed songs; throws on non-ok with the server `detail`.
```ts
import { describe, it, expect, vi } from "vitest";
import { uploadSongs } from "./api";

describe("uploadSongs", () => {
  it("returns songs on success", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true,
      json: async () => ({ songs: [{ id: "a", original_name: "x", url: "/songs/a/audio", status: "ready" }] }) }) as any;
    const out = await uploadSongs(new File([""], "x.wav"), new File([""], "y.wav"));
    expect(out.songs).toHaveLength(1);
  });
  it("throws server detail on failure", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: "nope" }) }) as any;
    await expect(uploadSongs(new File([""], "x"), new File([""], "y"))).rejects.toThrow("nope");
  });
});
```

- [ ] **Step 5: Minimal `App.tsx`, `main.tsx`, `index.html`, tsconfig, vite/vitest config** so `npm install` + `npm run typecheck` + `npm test` pass. `App.tsx` renders `<h1>Prompt-DJ</h1>` placeholder for now (Task 6 replaces it).

- [ ] **Step 6: Run** — `npm install` (root) then `npm run typecheck && npm test` → PASS.

- [ ] **Step 7: Commit** — `git add -A && git commit -m "feat(web): vite+react scaffold and API client"`

---

### Task 6: Uploader screen (Screen 1) with states + playback

**Files:**
- Create: `apps/web/src/components/Uploader/Uploader.tsx`, `apps/web/src/components/Uploader/Uploader.module.css`, `apps/web/src/components/Uploader/Uploader.test.tsx`
- Modify: `apps/web/src/App.tsx` (render `<Uploader/>`)

**Design note:** Before writing the UI, invoke the project UI/UX skill (`anthropic-skills:ui-ux-pro-max`) to guide layout, hierarchy, and the four states. Clean & product-looking (per approved design).

**Interfaces:**
- Consumes: `uploadSongs`, `SongDTO`, `API_BASE`.
- States: `empty` → `selected` → `processing` → `done` (two `<audio>` players) → `error` (message + retry).

- [ ] **Step 1: Write the failing component test** — `Uploader.test.tsx`
```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import * as api from "../../lib/api";
import { Uploader } from "./Uploader";

describe("Uploader", () => {
  it("disables Process until both files chosen", () => {
    render(<Uploader />);
    expect(screen.getByRole("button", { name: /process/i })).toBeDisabled();
  });

  it("shows two players after a successful upload", async () => {
    vi.spyOn(api, "uploadSongs").mockResolvedValue({ songs: [
      { id: "a", original_name: "beat.wav", url: "/songs/a/audio", status: "ready" },
      { id: "b", original_name: "voc.wav", url: "/songs/b/audio", status: "ready" },
    ]});
    render(<Uploader />);
    const [z1, z2] = screen.getAllByLabelText(/choose/i);
    fireEvent.change(z1, { target: { files: [new File([""], "beat.wav")] } });
    fireEvent.change(z2, { target: { files: [new File([""], "voc.wav")] } });
    fireEvent.click(screen.getByRole("button", { name: /process/i }));
    await waitFor(() => expect(screen.getAllByTestId("player")).toHaveLength(2));
  });

  it("shows an error message when upload fails", async () => {
    vi.spyOn(api, "uploadSongs").mockRejectedValue(new Error("not audio"));
    render(<Uploader />);
    const [z1, z2] = screen.getAllByLabelText(/choose/i);
    fireEvent.change(z1, { target: { files: [new File([""], "a")] } });
    fireEvent.change(z2, { target: { files: [new File([""], "b")] } });
    fireEvent.click(screen.getByRole("button", { name: /process/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/not audio/i));
  });
});
```

- [ ] **Step 2: Run, verify fail** → FAIL (no component).

- [ ] **Step 3: Implement `Uploader.tsx`** — two labeled file inputs ("Song 1 — the beat", "Song 2 — the vocals", each with an accessible `choose` label), a Process button (disabled until both set), a status region, and on success two `<audio data-testid="player" controls src={API_BASE + url}>`; on failure a `role="alert"` message + retry. Styling in `Uploader.module.css` per the UI/UX skill.

- [ ] **Step 4: Render `<Uploader/>` in `App.tsx`.**

- [ ] **Step 5: Run tests + typecheck, verify pass** → `npm test && npm run typecheck` → PASS.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(web): upload screen with states and playback"`

---

### Task 7: End-to-end run + docs + test sheet

**Files:**
- Modify: `docs/implementation-plan.md` (mark M1 done), `docs/technical-spec.md` (note as-built), `README.md` (create: how to run)

- [ ] **Step 1:** Start backend `cd services/api && python -m uvicorn app.main:app --reload` and web `npm -w apps/web run dev`; manually run the acceptance check with two real songs; confirm both play back.
- [ ] **Step 2:** Update `docs/implementation-plan.md` — M1 → done; append drift-log note (no DB in M1 as planned). Update `docs/technical-spec.md` "as-built" line. Create `README.md` with run instructions.
- [ ] **Step 3:** Write the plain-language test sheet (below) into the PR description.
- [ ] **Step 4: Commit** — `git add -A && git commit -m "docs(m1): mark skeleton done, add README + run steps"`

---

## Test sheet (for the human, on the running app)
1. Start the app (I'll give you one command). → A page titled Prompt-DJ with two boxes and a Process button.
2. The Process button is greyed out until you pick both songs. → Confirmed greyed out with zero or one song.
3. Drop an MP3/WAV in "Song 1" and another in "Song 2", click Process. → A short "processing…" state, then two players appear.
4. Press play on each. → Both songs play, at a consistent volume.
5. Try a non-audio file (e.g. a PDF). → A clear message that it isn't a supported audio file; no crash.

## Self-review
- **Spec coverage:** upload screen + states (T6), FFmpeg normalize (T2), content-hash storage (T3), validated upload + serve (T4), no DB/queue (honored), safety controls (T3/T4), tests with code (all tasks), acceptance (T7). ✓
- **Placeholders:** none — code shown for each logic file. ✓
- **Type consistency:** `Song{id,original_name,url,status}` ↔ `SongDTO` match; `normalize_audio(src,dst)`, `store_wav`, `path_for`, `uploadSongs` names consistent across tasks. ✓

import { useState } from "react";
import {
  API_BASE,
  getAnalysisStatus,
  getStemStatus,
  startAnalysis,
  startSplit,
  uploadSongs,
  type SongDTO,
  type TrackAnalysisDTO,
} from "../../lib/api";
import { MixMaker } from "../Mix/Mix";
import styles from "./Uploader.module.css";

type Status = "idle" | "processing" | "done" | "error";

export function Uploader() {
  const [file1, setFile1] = useState<File | null>(null);
  const [file2, setFile2] = useState<File | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [songs, setSongs] = useState<SongDTO[]>([]);
  const [error, setError] = useState("");

  const processing = status === "processing";
  const canProcess = Boolean(file1) && Boolean(file2) && !processing;

  async function handleProcess() {
    if (!file1 || !file2) return;
    setStatus("processing");
    setError("");
    try {
      const res = await uploadSongs(file1, file2);
      setSongs(res.songs);
      setStatus("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setStatus("error");
    }
  }

  return (
    <main className={styles.wrap}>
      <header className={styles.header}>
        <h1 className={styles.title}>Prompt-DJ</h1>
        <p className={styles.subtitle}>
          Drop two songs. We&rsquo;ll clean them up so you can play them back.
        </p>
      </header>

      <div className={styles.zones}>
        <DropZone
          label="Song 1 — the beat"
          file={file1}
          onPick={setFile1}
          disabled={processing}
        />
        <DropZone
          label="Song 2 — the vocals"
          file={file2}
          onPick={setFile2}
          disabled={processing}
        />
      </div>

      <button
        className={styles.process}
        onClick={handleProcess}
        disabled={!canProcess}
      >
        {processing ? "Processing…" : "Process"}
      </button>

      {status === "error" && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}

      {status === "done" && (
        <section className={styles.results}>
          {songs.map((s) => (
            <SongCard key={s.id} song={s} />
          ))}
          {songs.length === 2 && <MixMaker song1={songs[0]} song2={songs[1]} />}
        </section>
      )}
    </main>
  );
}

type StemStatus = "idle" | "splitting" | "done" | "error";
type AnalysisStatus = "idle" | "analyzing" | "done" | "error";

function SongCard({ song }: { song: SongDTO }) {
  const [stemStatus, setStemStatus] = useState<StemStatus>("idle");
  const [stems, setStems] = useState<Record<string, string>>({});
  const [stemError, setStemError] = useState("");
  const [anStatus, setAnStatus] = useState<AnalysisStatus>("idle");
  const [analysis, setAnalysis] = useState<TrackAnalysisDTO | null>(null);
  const [anError, setAnError] = useState("");

  async function handleAnalyze() {
    setAnStatus("analyzing");
    setAnError("");
    try {
      const started = await startAnalysis(song.id);
      if (started.status === "ready") {
        setAnalysis(started);
        setAnStatus("done");
        return;
      }
      // Poll until the cloud analysis finishes (cap ~5 minutes).
      for (let i = 0; i < 100; i++) {
        const s = await getAnalysisStatus(song.id);
        if (s.status === "ready") {
          setAnalysis(s);
          setAnStatus("done");
          return;
        }
        if (s.status === "error") {
          throw new Error("The analysis failed. Please try again.");
        }
        await new Promise((r) => setTimeout(r, 3000));
      }
      throw new Error("The analysis is taking too long. Please try again.");
    } catch (e) {
      setAnError(
        e instanceof Error ? e.message : "Couldn't analyze this song.",
      );
      setAnStatus("error");
    }
  }

  async function handleSplit() {
    setStemStatus("splitting");
    setStemError("");
    try {
      const started = await startSplit(song.id);
      if (started.status === "ready") {
        setStems(started.stems);
        setStemStatus("done");
        return;
      }
      // Poll until the cloud split finishes (cap ~4 minutes).
      for (let i = 0; i < 80; i++) {
        const s = await getStemStatus(song.id);
        if (s.status === "ready") {
          setStems(s.stems);
          setStemStatus("done");
          return;
        }
        if (s.status === "error") {
          throw new Error("The split failed. Please try again.");
        }
        await new Promise((r) => setTimeout(r, 3000));
      }
      throw new Error("The split is taking too long. Please try again.");
    } catch (e) {
      setStemError(
        e instanceof Error ? e.message : "Couldn't split this song.",
      );
      setStemStatus("error");
    }
  }

  return (
    <figure className={styles.player}>
      <figcaption className={styles.playerLabel}>
        {song.original_name}
      </figcaption>
      <audio
        data-testid="player"
        controls
        src={`${API_BASE}${song.url}`}
        className={styles.audio}
      />

      <div className={styles.actions}>
        {stemStatus === "idle" && (
          <button className={styles.splitBtn} onClick={handleSplit}>
            Split into parts
          </button>
        )}
        {anStatus === "idle" && (
          <button className={styles.splitBtn} onClick={handleAnalyze}>
            Analyze track
          </button>
        )}
      </div>

      {anStatus === "analyzing" && (
        <p className={styles.splitting}>
          Reading the track — beat, key, structure… (~1–2 min)
        </p>
      )}
      {anStatus === "error" && (
        <p role="alert" className={styles.error}>
          {anError}
        </p>
      )}
      {anStatus === "done" && analysis && <Insights analysis={analysis} />}
      {stemStatus === "splitting" && (
        <p className={styles.splitting}>
          Splitting into vocals, drums, bass &amp; other… (~30–60s)
        </p>
      )}
      {stemStatus === "error" && (
        <p role="alert" className={styles.error}>
          {stemError}
        </p>
      )}
      {stemStatus === "done" && (
        <div className={styles.stems}>
          {Object.entries(stems).map(([name, url]) => (
            <div key={name} className={styles.stem}>
              <span className={styles.stemName}>{name}</span>
              <audio
                data-testid="stem-player"
                controls
                src={`${API_BASE}${url}`}
                className={styles.audio}
              />
            </div>
          ))}
        </div>
      )}
    </figure>
  );
}

const SECTION_COLORS: Record<string, string> = {
  intro: "#4a5066",
  verse: "#5a67d8",
  chorus: "#7c5cff",
  bridge: "#00d3a7",
  inst: "#3d4a5c",
  solo: "#c084fc",
  break: "#2c3242",
  outro: "#4a5066",
  start: "#2c3242",
  end: "#2c3242",
};

function Insights({ analysis }: { analysis: TrackAnalysisDTO }) {
  const sections = analysis.sections ?? [];
  const total = sections.length ? sections[sections.length - 1].end : 0;

  return (
    <div className={styles.insights} data-testid="insights">
      <div className={styles.chips}>
        {analysis.bpm ? (
          <span className={styles.chip}>{Math.round(analysis.bpm)} BPM</span>
        ) : null}
        {analysis.key ? (
          <span
            className={styles.chipAccent}
            title={`${analysis.key.tonic} ${analysis.key.mode} — confidence ${Math.round(
              analysis.key.confidence * 100,
            )}%`}
          >
            Key {analysis.key.camelot}
          </span>
        ) : null}
      </div>
      {total > 0 && (
        <div
          className={styles.timeline}
          role="img"
          aria-label="Song structure timeline"
        >
          {sections.map((s, i) => {
            const width = ((s.end - s.start) / total) * 100;
            return (
              <div
                key={i}
                className={styles.segment}
                title={`${s.label} · ${Math.round(s.start)}s–${Math.round(s.end)}s`}
                style={{
                  width: `${width}%`,
                  background: SECTION_COLORS[s.label] ?? "#3d4a5c",
                }}
              >
                {width > 9 ? (
                  <span className={styles.segLabel}>{s.label}</span>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function DropZone({
  label,
  file,
  onPick,
  disabled,
}: {
  label: string;
  file: File | null;
  onPick: (f: File | null) => void;
  disabled: boolean;
}) {
  return (
    <label className={styles.zone}>
      <span className={styles.zoneLabel}>{label}</span>
      <span className={styles.zoneHint}>
        {file ? file.name : "Click to choose an audio file"}
      </span>
      <input
        className={styles.input}
        type="file"
        accept="audio/*"
        aria-label={`Choose ${label}`}
        disabled={disabled}
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
      />
    </label>
  );
}

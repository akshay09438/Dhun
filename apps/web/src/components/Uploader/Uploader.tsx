import { useState } from "react";
import {
  API_BASE,
  getStemStatus,
  startSplit,
  uploadSongs,
  type SongDTO,
} from "../../lib/api";
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
        </section>
      )}
    </main>
  );
}

type StemStatus = "idle" | "splitting" | "done" | "error";

function SongCard({ song }: { song: SongDTO }) {
  const [stemStatus, setStemStatus] = useState<StemStatus>("idle");
  const [stems, setStems] = useState<Record<string, string>>({});
  const [stemError, setStemError] = useState("");

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

      {stemStatus === "idle" && (
        <button className={styles.splitBtn} onClick={handleSplit}>
          🎛️ Split into parts
        </button>
      )}
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

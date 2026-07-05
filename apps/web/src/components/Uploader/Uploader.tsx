import { useState } from "react";
import { API_BASE, uploadSongs, type SongDTO } from "../../lib/api";
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
            <figure key={s.id} className={styles.player}>
              <figcaption className={styles.playerLabel}>
                {s.original_name}
              </figcaption>
              <audio
                data-testid="player"
                controls
                src={`${API_BASE}${s.url}`}
                className={styles.audio}
              />
            </figure>
          ))}
        </section>
      )}
    </main>
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

import { useState } from "react";
import { uploadSongs, type MixDTO, type SongDTO } from "../../lib/api";
import { studyAndMix, STUDY_STEPS, type StudyStage } from "../../lib/study";
import { MixMaker } from "../Mix/Mix";
import LiveMix from "../Live/LiveMix";
import styles from "./Uploader.module.css";

type Phase = "idle" | "studying" | "mix";

export function Uploader() {
  const [file1, setFile1] = useState<File | null>(null);
  const [file2, setFile2] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [stage, setStage] = useState<StudyStage>("uploading");
  const [songs, setSongs] = useState<SongDTO[]>([]);
  const [mix, setMix] = useState<MixDTO | null>(null);
  const [mixId, setMixId] = useState<string | undefined>(undefined);
  const [error, setError] = useState("");

  const busy = phase === "studying";
  const canMix = Boolean(file1) && Boolean(file2) && !busy;

  async function handleMakeMix() {
    if (!file1 || !file2) return;
    setPhase("studying");
    setStage("uploading");
    setError("");
    try {
      const res = await uploadSongs(file1, file2);
      setSongs(res.songs);
      // One hands-free step: split + analyze both songs (in the right order),
      // then plan the mix. `setStage` drives the honest progress checklist.
      const made = await studyAndMix(
        res.songs[0].id,
        res.songs[1].id,
        setStage,
      );
      setMix(made);
      setMixId(made.mix_id);
      setPhase("mix");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    }
  }

  function startOver() {
    setPhase("idle");
    setError("");
    setSongs([]);
    setMix(null);
    setMixId(undefined);
  }

  return (
    <main className={styles.wrap}>
      <header className={styles.header}>
        <h1 className={styles.title}>Prompt-DJ</h1>
        <p className={styles.subtitle}>
          Drop two songs and we&rsquo;ll make you a DJ-style mix.
        </p>
      </header>

      {phase === "idle" && (
        <>
          <div className={styles.zones}>
            <DropZone
              label="Song 1 — the beat"
              file={file1}
              onPick={setFile1}
              disabled={busy}
            />
            <DropZone
              label="Song 2 — the vocals"
              file={file2}
              onPick={setFile2}
              disabled={busy}
            />
          </div>

          <button
            className={styles.process}
            onClick={handleMakeMix}
            disabled={!canMix}
          >
            Make my mix
          </button>
        </>
      )}

      {phase === "studying" && (
        <StudyingScreen stage={stage} error={error} onStartOver={startOver} />
      )}

      {phase === "mix" && songs.length === 2 && mix && (
        <section className={styles.results}>
          <MixMaker
            song1={songs[0]}
            song2={songs[1]}
            initialMix={mix}
            onMixReady={setMixId}
          />
          <LiveMix song1Id={songs[0].id} song2Id={songs[1].id} mixId={mixId} />
        </section>
      )}
    </main>
  );
}

/** The "Studying your songs" wait: an honest checklist that ticks off in order. */
function StudyingScreen({
  stage,
  error,
  onStartOver,
}: {
  stage: StudyStage;
  error: string;
  onStartOver: () => void;
}) {
  const current = STUDY_STEPS.findIndex((s) => s.stage === stage);

  if (error) {
    return (
      <section className={styles.studying} data-testid="studying">
        <p role="alert" className={styles.error}>
          {error}
        </p>
        <button className={styles.process} onClick={onStartOver}>
          Start over
        </button>
      </section>
    );
  }

  return (
    <section className={styles.studying} data-testid="studying">
      <h2 className={styles.studyingTitle}>Studying your songs…</h2>
      <ol className={styles.steps}>
        {STUDY_STEPS.map((step, i) => {
          const done = i < current;
          const active = i === current;
          const cls = done
            ? `${styles.step} ${styles.stepDone}`
            : active
              ? `${styles.step} ${styles.stepActive}`
              : styles.step;
          return (
            <li key={step.stage} className={cls}>
              <span className={styles.stepIcon} aria-hidden="true">
                {done ? "✓" : active ? "⟳" : "•"}
              </span>
              {step.label}
            </li>
          );
        })}
      </ol>
      <p className={styles.splitting}>
        First time takes about a minute; after that it&rsquo;s instant.
      </p>
    </section>
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

import { useState } from "react";
import {
  API_BASE,
  getMixStatus,
  startMix,
  type MixDTO,
  type SongDTO,
} from "../../lib/api";
import styles from "./Mix.module.css";

type MixState = "idle" | "mixing" | "done" | "error";

/**
 * The heart of M3: turn the two ready songs into one finished mix — Song 1's beat
 * with Song 2's vocal dropped in on the beat — then play and download it. Requires
 * both songs to be analyzed and split first; if they aren't, the backend says so in
 * plain language and we surface it.
 */
export function MixMaker({ song1, song2 }: { song1: SongDTO; song2: SongDTO }) {
  const [state, setState] = useState<MixState>("idle");
  const [mix, setMix] = useState<MixDTO | null>(null);
  const [error, setError] = useState("");

  async function handleMix() {
    setState("mixing");
    setError("");
    setMix(null);
    try {
      const started = await startMix(song1.id, song2.id);
      if (started.status === "ready") {
        setMix(started);
        setState("done");
        return;
      }
      // Poll until the mix is rendered (cap ~4 minutes).
      for (let i = 0; i < 80; i++) {
        const s = await getMixStatus(started.mix_id);
        if (s.status === "ready") {
          setMix(s);
          setState("done");
          return;
        }
        if (s.status === "error") {
          throw new Error(
            s.message ?? "This pair couldn't be mixed. Try another.",
          );
        }
        await new Promise((r) => setTimeout(r, 3000));
      }
      throw new Error("The mix is taking too long. Please try again.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't make the mix.");
      setState("error");
    }
  }

  async function handleDownload() {
    if (!mix?.url) return;
    const res = await fetch(`${API_BASE}${mix.url}`);
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = "prompt-dj-mix.wav";
    a.click();
    URL.revokeObjectURL(href);
  }

  return (
    <section className={styles.wrap} data-testid="mix">
      <h2 className={styles.heading}>Make your mix</h2>
      <p className={styles.hint}>
        Song 1&rsquo;s beat with Song 2&rsquo;s vocal, dropped in on the beat
        like a DJ.
      </p>

      {state !== "done" && (
        <button
          className={styles.make}
          onClick={handleMix}
          disabled={state === "mixing"}
        >
          {state === "mixing" ? "Mixing…" : "Make my mix"}
        </button>
      )}

      {state === "mixing" && (
        <p className={styles.progress}>
          Beat-matching and arranging your mix… (~1–2 min)
        </p>
      )}

      {state === "error" && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}

      {state === "done" && mix?.url && (
        <div className={styles.result}>
          {mix.plan?.notes && <p className={styles.notes}>{mix.plan.notes}</p>}
          <span className={styles.badge}>
            {mix.plan?.source === "ai" ? "AI DJ" : "DJ rules"}
          </span>
          <audio
            data-testid="mix-player"
            controls
            src={`${API_BASE}${mix.url}`}
            className={styles.audio}
          />
          <button className={styles.download} onClick={handleDownload}>
            Download the mix
          </button>
        </div>
      )}
    </section>
  );
}

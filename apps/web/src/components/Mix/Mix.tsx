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
 * The heart of M4: turn the two ready songs into a full DJ arrangement — Song 1's
 * beat running throughout with Song 2's vocal weaving in and out — then show the
 * arrangement, let the user regenerate a different take, and download it.
 */
export function MixMaker({ song1, song2 }: { song1: SongDTO; song2: SongDTO }) {
  const [state, setState] = useState<MixState>("idle");
  const [mix, setMix] = useState<MixDTO | null>(null);
  const [error, setError] = useState("");

  async function handleMix(take = 1) {
    setState("mixing");
    setError("");
    setMix(null);
    try {
      const started = await startMix(song1.id, song2.id, "", take);
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

  const take = mix?.plan?.take ?? 1;

  return (
    <section className={styles.wrap} data-testid="mix">
      <h2 className={styles.heading}>Make your mix</h2>
      <p className={styles.hint}>
        Song 1&rsquo;s beat with Song 2&rsquo;s vocal, arranged in and out like
        a DJ.
      </p>

      {state === "idle" && (
        <button className={styles.make} onClick={() => handleMix(1)}>
          Make my mix
        </button>
      )}

      {state === "mixing" && (
        <p className={styles.progress}>
          Beat-matching and arranging your mix&hellip; (~1&ndash;2 min)
        </p>
      )}

      {state === "error" && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}

      {state === "done" && mix?.url && (
        <div className={styles.result}>
          <div className={styles.resultHead}>
            {mix.plan?.notes && (
              <p className={styles.notes}>{mix.plan.notes}</p>
            )}
            <span className={styles.badge}>take {take}</span>
          </div>

          <Arrangement mix={mix} />

          <audio
            data-testid="mix-player"
            controls
            src={`${API_BASE}${mix.url}`}
            className={styles.audio}
          />

          <div className={styles.actions}>
            <button
              className={styles.regenerate}
              onClick={() => handleMix(take + 1)}
            >
              Give me another take
            </button>
            <button className={styles.download} onClick={handleDownload}>
              Download the mix
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/** The two-lane arrangement view: the beat runs throughout; the vocal comes in and out. */
function Arrangement({ mix }: { mix: MixDTO }) {
  const placements = mix.plan?.placements ?? [];
  const stretch = mix.plan?.vocal_stretch ?? 1;
  if (placements.length === 0) return null;

  const blocks = placements.map((p) => {
    const start = p.anchor;
    const end = p.anchor + (p.vocal_src[1] - p.vocal_src[0]) * stretch;
    return { start, end, breath: p.beat_breath };
  });
  const total = Math.max(...blocks.map((b) => b.end), 1);

  return (
    <div
      className={styles.timeline}
      role="img"
      aria-label="Arrangement timeline"
    >
      <div className={styles.lane}>
        <span className={styles.laneLabel}>beat</span>
        <div className={styles.beatBar}>plays throughout</div>
      </div>
      <div className={styles.lane}>
        <span className={styles.laneLabel}>vocal</span>
        <div className={styles.vocalTrack}>
          {blocks.map((b, i) => (
            <div
              key={i}
              data-testid="vocal-block"
              className={styles.vocalBlock}
              title={
                b.breath
                  ? "vocal in (with a beat-breath before it)"
                  : "vocal in"
              }
              style={{
                left: `${(b.start / total) * 100}%`,
                width: `${((b.end - b.start) / total) * 100}%`,
              }}
            >
              {b.breath ? "⤳" : ""}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

import { useState } from "react";
import { API_BASE, makeMix, type MixDTO, type SongDTO } from "../../lib/api";
import styles from "./Mix.module.css";

type MixState = "idle" | "mixing" | "done" | "error";

/**
 * The heart of M4: turn the two ready songs into a full DJ arrangement — Song 1's
 * beat running throughout with Song 2's vocal weaving in and out — then show the
 * arrangement, let the user regenerate a different take, and download it.
 *
 * `initialMix` lets the one-click studying flow hand in an already-rendered mix so
 * this shows the result straight away; Regenerate still makes fresh takes.
 */
export function MixMaker({
  song1,
  song2,
  onMixReady,
  initialMix,
}: {
  song1: SongDTO;
  song2: SongDTO;
  onMixReady?: (mixId: string) => void;
  initialMix?: MixDTO;
}) {
  const [state, setState] = useState<MixState>(initialMix ? "done" : "idle");
  const [mix, setMix] = useState<MixDTO | null>(initialMix ?? null);
  const [error, setError] = useState("");

  async function handleMix(take = 1) {
    setState("mixing");
    setError("");
    setMix(null);
    try {
      const s = await makeMix(song1.id, song2.id, "", take);
      setMix(s);
      setState("done");
      onMixReady?.(s.mix_id);
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

/** The two-lane arrangement view: the beat runs throughout; Song 2's vocal weaves in
 *  and out, and (Slice B) Song 1's own vocal answers in the gaps, in a distinct colour. */
function Arrangement({ mix }: { mix: MixDTO }) {
  const plan = mix.plan;
  const placements = plan?.placements ?? [];
  const stretch = plan?.vocal_stretch ?? 1;
  if (placements.length === 0) return null;

  const s2 = placements.map((p) => ({
    start: p.anchor,
    end: p.anchor + (p.vocal_src[1] - p.vocal_src[0]) / stretch, // real rendered length
    breath: p.beat_breath,
    fx: p.fx,
  }));
  const s1 = (plan?.s1_vocal_regions ?? []).map(([start, end]) => ({
    start,
    end,
  }));
  const total = Math.max(...s2.map((b) => b.end), ...s1.map((b) => b.end), 1);
  const pct = (x: number) => `${(x / total) * 100}%`;

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
          {s1.map((b, i) => (
            <div
              key={`s1-${i}`}
              data-testid="s1-vocal-block"
              className={styles.s1VocalBlock}
              title="Song 1's own vocal answers here (contrast)"
              style={{ left: pct(b.start), width: pct(b.end - b.start) }}
            />
          ))}
          {s2.map((b, i) => (
            <div
              key={`s2-${i}`}
              data-testid="vocal-block"
              className={styles.vocalBlock}
              title={
                b.fx
                  ? "vocal in (filter sweep builds into it)"
                  : b.breath
                    ? "vocal in (beat-breath before it)"
                    : "vocal in"
              }
              style={{ left: pct(b.start), width: pct(b.end - b.start) }}
            >
              {b.fx ? "∿" : b.breath ? "⤳" : ""}
            </div>
          ))}
        </div>
      </div>
      <p className={styles.legend}>
        <span className={styles.swatchS2} /> Song 2 vocal
        <span className={styles.swatchS1} /> Song 1 vocal
      </p>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { TrackPlayer } from "../../lib/trackAudio";
import type { PlayMember } from "../../types";
import styles from "./PlayScreen.module.css";

function fmt(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Decorative lane bars — the Play screen no longer steers stems, so these are a visual
 *  waveform, not a control surface. BEAT drives throughout; VOX clusters where a vocal sits. */
function laneBars(n = 40) {
  const beat: number[] = [];
  const vox: number[] = [];
  for (let i = 0; i < n; i++) {
    beat.push(45 + Math.abs(Math.sin(i / 1.7)) * 45);
    vox.push(
      (i > 8 && i < 19) || (i > 26 && i < 34) ? 90 : i > 19 && i < 26 ? 52 : 12,
    );
  }
  return { beat, vox };
}

export default function PlayScreen({
  title,
  audioUrl,
  members,
  regenerable,
  regenerating,
  onRegenerate,
  onExport,
  onNextSong,
}: {
  title: string;
  audioUrl: string;
  members: PlayMember[];
  regenerable: boolean;
  regenerating: boolean;
  onRegenerate: () => void;
  onExport: () => void;
  onNextSong: () => void;
}) {
  const heading = title || "Untitled Mix";

  const playerRef = useRef<TrackPlayer | null>(null);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true); // true while the track is buffering
  const [playing, setPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [duration, setDuration] = useState(0);
  const [dragging, setDragging] = useState(false);
  const scrubRef = useRef<HTMLDivElement>(null);

  const { beat, vox } = useMemo(() => laneBars(), []);
  const kept = members.filter((m) => m.kept);
  const dropped = members.filter((m) => !m.kept);
  const isSet = kept.length > 1;

  // (Re)load the track when the audio source changes.
  useEffect(() => {
    setReady(false);
    setLoading(true);
    setPlaying(false);
    setElapsed(0);
    setDuration(0);
    const p = new TrackPlayer(audioUrl);
    playerRef.current = p;
    p.on("ended", () => setPlaying(false));
    p.whenReady().then(() => {
      setReady(true);
      setLoading(false);
      setDuration(p.duration());
    });
    return () => p.dispose();
  }, [audioUrl]);

  // Follow the playhead while playing.
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const p = playerRef.current;
      if (!p) return;
      setElapsed(p.currentTime());
      const d = p.duration();
      if (d && d !== duration) setDuration(d);
    }, 250);
    return () => clearInterval(id);
  }, [playing, duration]);

  // Which set is playing now, by seam time (the opening set has no seam).
  const nowIndex = useMemo(() => {
    let idx = 0;
    kept.forEach((m, i) => {
      if (m.seamAt != null && elapsed >= m.seamAt) idx = i;
    });
    return idx;
  }, [kept, elapsed]);
  const nowMember = kept[nowIndex] ?? members[0];

  const dur = duration || playerRef.current?.duration() || 0;

  function seekToClientX(clientX: number) {
    const el = scrubRef.current;
    if (!el || !dur) return;
    const rect = el.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const t = frac * dur;
    playerRef.current?.seek(t);
    setElapsed(t);
  }

  // While dragging the scrub, follow the pointer anywhere until release.
  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => seekToClientX(e.clientX);
    const up = () => setDragging(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [dragging, dur]);

  function togglePlay() {
    const p = playerRef.current;
    if (!p) return;
    if (playing) {
      p.pause();
      setPlaying(false);
    } else {
      p.play();
      setPlaying(true);
    }
  }

  return (
    <>
      <div className="console">
        <div className={styles.consoleHead}>
          <p className="kicker">Session</p>
          <button
            type="button"
            className={styles.nextSong}
            data-testid="next-song"
            onClick={onNextSong}
            title="Start a new mix"
          >
            ＋ Next song
          </button>
        </div>
        <h1 className={`title ${styles.mixTitle}`} title={heading}>
          {heading}
        </h1>

        <div className={styles.setPanelHead}>
          <span>{isSet ? "Your set" : "Now playing"}</span>
          {isSet && <span>{kept.length} back-to-back</span>}
        </div>
        <div className={styles.setStack} data-testid="set-lineup">
          {kept.map((m, i) => (
            <div
              key={m.index}
              className={
                i === nowIndex
                  ? `${styles.qcard} ${styles.qcardNow}`
                  : styles.qcard
              }
              data-testid={`lineup-${m.index}`}
            >
              <span className={styles.qi}>Set {m.index}</span>
              <div className={styles.qp}>
                <div className={styles.qt} title={`${m.beat} × ${m.vocal}`}>
                  {m.beat} × {m.vocal}
                </div>
                <div className={styles.qs}>
                  {i === nowIndex
                    ? "now playing"
                    : i > nowIndex
                      ? "up next · chains on the beat"
                      : "played"}
                </div>
              </div>
              {i === nowIndex && <span className={styles.qnow}>▶ NOW</span>}
            </div>
          ))}
          {dropped.map((m) => (
            <div
              key={m.index}
              className={`${styles.qcard} ${styles.qcardDropped}`}
              data-testid={`lineup-${m.index}`}
            >
              <span className={styles.qi}>Set {m.index}</span>
              <div className={styles.qp}>
                <div className={styles.qt} title={`${m.beat} × ${m.vocal}`}>
                  {m.beat} × {m.vocal}
                </div>
                <div className={styles.qsDrop}>
                  {m.reason ?? "left out of the set"}
                </div>
              </div>
              <span className={styles.qskip}>skipped</span>
            </div>
          ))}
        </div>
      </div>

      <div className="stage">
        <div className={styles.live} data-live={playing}>
          <span className={styles.liveDot} />
          LIVE
        </div>
        <h2 className={styles.stageTitle} title={heading}>
          {heading}
        </h2>
        <div className={styles.stageSub}>
          BEAT · {nowMember?.beat}&nbsp;&nbsp;/&nbsp;&nbsp;VOX ·{" "}
          {nowMember?.vocal}
        </div>

        <div className={styles.lanes}>
          {loading && (
            <div
              className={styles.loading}
              role="status"
              aria-live="polite"
              data-testid="mix-loading"
            >
              <span className={styles.loadDot} />
              Loading your {isSet ? "set" : "mix"}…
            </div>
          )}
          <Lane label="BEAT" bars={beat} />
          <Lane label="VOX" bars={vox} dim />
        </div>

        <div className={styles.transport}>
          <button
            type="button"
            className={styles.playbtn}
            disabled={!ready}
            onClick={togglePlay}
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <div
            className={styles.scrub}
            ref={scrubRef}
            role="slider"
            aria-label="Seek through the mix"
            aria-valuemin={0}
            aria-valuemax={Math.round(dur)}
            aria-valuenow={Math.round(elapsed)}
            tabIndex={0}
            onPointerDown={(e) => {
              setDragging(true);
              seekToClientX(e.clientX);
            }}
            onKeyDown={(e) => {
              if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
              e.preventDefault();
              const t = Math.max(
                0,
                Math.min(dur, elapsed + (e.key === "ArrowRight" ? 5 : -5)),
              );
              playerRef.current?.seek(t);
              setElapsed(t);
            }}
          >
            <div className={styles.scrubTrack}>
              <i
                style={{
                  width: `${dur ? Math.min(100, (elapsed / dur) * 100) : 0}%`,
                }}
              />
            </div>
            {/* seam markers: where each later set joins the timeline */}
            {isSet &&
              kept.map((m) =>
                m.seamAt != null && dur ? (
                  <span
                    key={m.index}
                    className={styles.seamMark}
                    data-testid={`seam-${m.index}`}
                    style={{
                      left: `${Math.min(100, (m.seamAt / dur) * 100)}%`,
                    }}
                    title={`Set ${m.index} joins here`}
                  />
                ) : null,
              )}
            <span
              className={styles.knob}
              style={{
                left: `${dur ? Math.min(100, (elapsed / dur) * 100) : 0}%`,
              }}
            />
          </div>
          <span className={styles.time}>
            {fmt(elapsed)} / {fmt(dur)}
          </span>
          {regenerable && (
            <button
              type="button"
              className={styles.regen}
              disabled={regenerating}
              onClick={onRegenerate}
            >
              {regenerating ? "arranging…" : "↻ another take"}
            </button>
          )}
          <button
            type="button"
            className={styles.exportlink}
            onClick={onExport}
          >
            export
          </button>
        </div>
      </div>
    </>
  );
}

function Lane({
  label,
  bars,
  dim,
}: {
  label: string;
  bars: number[];
  dim?: boolean;
}) {
  return (
    <div className={styles.lane}>
      <span className={styles.laneLbl}>{label}</span>
      <div className={styles.lanebars} role="img" aria-label={`${label} lane`}>
        {bars.map((h, i) => (
          <span
            key={i}
            style={{ height: `${h}%`, opacity: dim && h < 25 ? 0.35 : 1 }}
          />
        ))}
      </div>
    </div>
  );
}

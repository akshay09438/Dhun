import { useEffect, useMemo, useRef, useState } from "react";
import { LivePlayer } from "../../lib/liveAudio";
import {
  getLiveContext,
  getSuggestions,
  postLiveCommand,
  type LiveContextDTO,
  type LiveOpDTO,
  type MixDTO,
  type SectionSuggestionsDTO,
  type SongDTO,
} from "../../lib/api";
import {
  applyOp,
  currentChips,
  type BusName,
  type BusState,
  type Chip,
} from "../../lib/liveSchedule";
import styles from "./PlayScreen.module.css";

const STEM_BUSES: BusName[] = ["drums", "bass", "other"];
const PARTS: { bus: BusName; label: string }[] = [
  { bus: "drums", label: "Beat" },
  { bus: "bass", label: "Bass" },
  { bus: "other", label: "Melody" },
  { bus: "vocals", label: "Vocals" },
];

type FeedLine = { text: string; kind: "user" | "system" };

function fmt(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Lane bars for the arrangement view: BEAT plays throughout; VOX clusters where the
 *  vocal actually enters (Song 2 placements + Song 1 contrast) — proof it's arranged. */
function laneBars(mix: MixDTO, n = 40) {
  const plan = mix.plan;
  const placements = plan?.placements ?? [];
  const stretch = plan?.vocal_stretch ?? 1;
  const s2 = placements.map((p) => ({
    start: p.anchor,
    end: p.anchor + (p.vocal_src[1] - p.vocal_src[0]) / stretch,
  }));
  const s1 = (plan?.s1_vocal_regions ?? []).map(([start, end]) => ({
    start,
    end,
  }));
  const total = Math.max(1, ...s2.map((b) => b.end), ...s1.map((b) => b.end));
  const inAny = (t: number, ws: { start: number; end: number }[]) =>
    ws.some((w) => t >= w.start && t <= w.end);

  const beat: number[] = [];
  const vox: number[] = [];
  for (let i = 0; i < n; i++) {
    const t = (i / n) * total;
    beat.push(45 + Math.abs(Math.sin(i / 1.7)) * 45); // steady drive
    vox.push(inAny(t, s2) ? 90 : inAny(t, s1) ? 55 : 12);
  }
  return { beat, vox, total };
}

export default function PlayScreen({
  songs,
  mix,
  mixId,
  mixName,
  regenerating,
  onRegenerate,
  onExport,
}: {
  songs: SongDTO[];
  mix: MixDTO;
  mixId?: string;
  mixName: string;
  regenerating: boolean;
  onRegenerate: () => void;
  onExport: () => void;
}) {
  const song1Id = songs[0].id;
  const song2Id = songs[1].id;
  const title = mixName || "Untitled Mix";

  const playerRef = useRef<LivePlayer | null>(null);
  const ctxRef = useRef<LiveContextDTO>({ bpm: 120, downbeats: [] });
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [busState, setBusState] = useState<BusState>({
    drums: true,
    bass: true,
    other: true,
    vocals: true,
  });
  const [feed, setFeed] = useState<FeedLine[]>([]);
  const [text, setText] = useState("");
  const [sections, setSections] = useState<SectionSuggestionsDTO[]>([]);
  const [chips, setChips] = useState<Chip[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [dragging, setDragging] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);
  const scrubRef = useRef<HTMLDivElement>(null);

  const { beat, vox, total } = useMemo(() => laneBars(mix), [mix]);

  // (Re)load the player when the song or take changes, so live vocals match the mix.
  useEffect(() => {
    setReady(false);
    setPlaying(false);
    let p: LivePlayer;
    try {
      p = new LivePlayer();
    } catch {
      return; // no Web Audio (or test DOM) — stays not-ready, no crash
    }
    playerRef.current = p;
    Promise.all([p.load(song1Id, STEM_BUSES, mixId), getLiveContext(song1Id)])
      .then(([, ctx]) => {
        ctxRef.current = ctx;
        setReady(true);
      })
      .catch(() => setReady(false));
    return () => p.dispose();
  }, [song1Id, mixId]);

  // Load per-section suggestion chips once per take.
  useEffect(() => {
    setSections([]);
    setChips([]);
    if (!mixId) return;
    getSuggestions(mixId)
      .then(setSections)
      .catch(() => setSections([]));
  }, [mixId]);

  // Follow the playhead while playing: current chips + elapsed time for the transport.
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const t = playerRef.current?.songTime() ?? 0;
      setElapsed(t);
      if (sections.length) setChips(currentChips(sections, t));
    }, 250);
    return () => clearInterval(id);
  }, [playing, sections]);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight; // keep the newest reply in view
  }, [feed]);

  const duration = playerRef.current?.duration() || total;

  function seekToClientX(clientX: number) {
    const el = scrubRef.current;
    if (!el || !duration) return;
    const rect = el.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const t = frac * duration;
    playerRef.current?.seek(t);
    setElapsed(t);
  }

  // While dragging the scrub, follow the pointer anywhere on the page until release.
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
  }, [dragging, duration]);

  function say(text: string, kind: FeedLine["kind"]) {
    setFeed((f) => [...f, { text, kind }]);
  }

  function runOp(op: LiveOpDTO) {
    if (
      op.op === "mute" ||
      op.op === "unmute" ||
      op.op === "fade" ||
      op.op === "beat_up"
    ) {
      playerRef.current?.schedule(op, ctxRef.current);
      setBusState((s) => applyOp(s, op));
    }
  }

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

  function toggleBus(bus: BusName) {
    const muting = busState[bus];
    const op: LiveOpDTO = {
      op: muting ? "mute" : "unmute",
      target: bus,
      targets: [bus],
      when: "next_bar",
      say: "",
      reason: null,
    };
    runOp(op);
    const label = PARTS.find((p) => p.bus === bus)?.label.toLowerCase() ?? bus;
    say(
      `→ ${muting ? "dropped" : "brought back"} the ${label}, next beat`,
      "system",
    );
  }

  function beatUp() {
    runOp({
      op: "beat_up",
      target: null,
      targets: ["other", "vocals"],
      when: "next_bar",
      say: "",
      reason: null,
    });
    say("→ beat takes over, on next beat", "system");
  }

  function tapChip(chip: Chip) {
    runOp({
      op: chip.op as LiveOpDTO["op"],
      target: chip.targets.length === 1 ? chip.targets[0] : null,
      targets: chip.targets,
      when: "next_bar",
      say: "",
      reason: null,
    });
    say(`→ ${chip.text.toLowerCase()}, on next beat`, "system");
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    say(t, "user");
    setText("");
    const op = await postLiveCommand(song1Id, song2Id, t);
    say(`→ ${op.say}`, "system");
    runOp(op);
  }

  return (
    <>
      <div className="console">
        <p className="kicker">Session</p>
        <h1 className={`title ${styles.mixTitle}`} title={title}>
          {title}
        </h1>

        <div className={styles.feed} ref={feedRef}>
          {feed.length === 0 && (
            <div className={styles.feedHint}>
              Tap a part, a suggestion, or type a command below.
            </div>
          )}
          {feed.map((l, i) => (
            <div
              key={i}
              className={l.kind === "system" ? styles.sysLine : styles.userLine}
            >
              {l.text}
            </div>
          ))}
        </div>

        <div className={styles.ctlLabel}>Parts</div>
        <div className={styles.parts}>
          {PARTS.map(({ bus, label }) => (
            <button
              key={bus}
              type="button"
              data-testid={`bus-${bus}`}
              className={busState[bus] ? styles.part : styles.partOff}
              onClick={() => toggleBus(bus)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className={styles.moves}>
          <button
            type="button"
            data-testid="beat-up"
            className={styles.chipHot}
            onClick={beatUp}
          >
            Beat up
          </button>
          {chips.map((c) => (
            <button
              key={c.text}
              type="button"
              data-testid="suggestion-chip"
              className={styles.chip}
              onClick={() => tapChip(c)}
            >
              {c.text}
            </button>
          ))}
        </div>

        <form
          className={styles.cmdbar}
          aria-label="command"
          onSubmit={onSubmit}
        >
          <input
            placeholder="tell the mix what to do…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button type="submit" className={styles.send} aria-label="Send">
            ▸
          </button>
        </form>
      </div>

      <div className="stage">
        <div className={styles.live} data-live={playing}>
          <span className={styles.liveDot} />
          LIVE
        </div>
        <h2 className={styles.stageTitle} title={title}>
          {title}
        </h2>
        <div className={styles.stageSub}>
          BEAT · {songs[0].original_name}&nbsp;&nbsp;/&nbsp;&nbsp;VOX ·{" "}
          {songs[1].original_name}
        </div>

        <div className={styles.lanes}>
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
            aria-valuemax={Math.round(duration)}
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
                Math.min(duration, elapsed + (e.key === "ArrowRight" ? 5 : -5)),
              );
              playerRef.current?.seek(t);
              setElapsed(t);
            }}
          >
            <div className={styles.scrubTrack}>
              <i
                style={{
                  width: `${duration ? Math.min(100, (elapsed / duration) * 100) : 0}%`,
                }}
              />
            </div>
            <span
              className={styles.knob}
              style={{
                left: `${duration ? Math.min(100, (elapsed / duration) * 100) : 0}%`,
              }}
            />
          </div>
          <span className={styles.time}>
            {fmt(elapsed)} / {fmt(duration)}
          </span>
          <button
            type="button"
            className={styles.regen}
            disabled={regenerating}
            onClick={onRegenerate}
          >
            {regenerating ? "arranging…" : "↻ another take"}
          </button>
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

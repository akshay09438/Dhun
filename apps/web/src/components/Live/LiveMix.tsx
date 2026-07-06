import { useEffect, useRef, useState } from "react";
import { LivePlayer } from "../../lib/liveAudio";
import {
  postLiveCommand,
  getLiveContext,
  type LiveContextDTO,
  type LiveOpDTO,
} from "../../lib/api";
import { applyOp, type BusState, type BusName } from "../../lib/liveSchedule";
import styles from "./LiveMix.module.css";

const STEM_BUSES: BusName[] = ["drums", "bass", "other"];
// Display order + friendly labels for the four controllable parts.
const PARTS: { bus: BusName; label: string }[] = [
  { bus: "drums", label: "Beat" },
  { bus: "bass", label: "Bass" },
  { bus: "other", label: "Melody" },
  { bus: "vocals", label: "Vocals" },
];

export default function LiveMix({
  song1Id,
  song2Id,
  mixId,
}: {
  song1Id: string;
  song2Id: string;
  mixId?: string;
}) {
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
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");

  // (Re)load the player whenever the song or the current take (mixId) changes, so the
  // live vocals always match the mix on screen.
  useEffect(() => {
    setReady(false);
    setPlaying(false);
    let p: LivePlayer;
    try {
      p = new LivePlayer();
    } catch {
      return; // no Web Audio (or a test DOM) — live mode stays not-ready, page doesn't crash
    }
    playerRef.current = p;
    Promise.all([
      p.load(song1Id, STEM_BUSES, mixId),
      getLiveContext(song1Id),
    ]).then(([, ctx]) => {
      ctxRef.current = ctx;
      setReady(true);
    });
    return () => p.dispose();
  }, [song1Id, mixId]);

  const vocalsAvailable = Boolean(mixId);

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

  /** Apply an op to the audio + the on/off state (shared by taps and typed commands). */
  function runOp(op: LiveOpDTO) {
    if (op.op === "mute" || op.op === "unmute") {
      playerRef.current?.schedule(op, ctxRef.current);
      setBusState((s) => applyOp(s, op));
    }
  }

  function toggleBus(bus: BusName) {
    if (bus === "vocals" && !vocalsAvailable) return;
    const op: LiveOpDTO = {
      op: busState[bus] ? "mute" : "unmute",
      target: bus,
      targets: [bus],
      when: "next_bar",
      say: "",
      reason: null,
    };
    runOp(op);
    // Reply with the friendly part name ("the beat"), not the raw bus key ("the other").
    const label = PARTS.find((p) => p.bus === bus)?.label.toLowerCase() ?? bus;
    setStatus(
      `${busState[bus] ? "dropping" : "bringing back"} the ${label} on the next bar`,
    );
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    const op = await postLiveCommand(song1Id, song2Id, text);
    setStatus(op.say);
    runOp(op);
    setText("");
  }

  return (
    <div className={styles.live}>
      <button onClick={togglePlay} disabled={!ready}>
        {playing ? "Pause" : "Play"}
      </button>
      <div className={styles.buses}>
        {PARTS.map(({ bus, label }) => {
          const disabled = bus === "vocals" && !vocalsAvailable;
          return (
            <button
              key={bus}
              type="button"
              data-testid={`bus-${bus}`}
              data-on={busState[bus]}
              className={busState[bus] ? styles.on : styles.off}
              disabled={disabled}
              title={
                disabled
                  ? "Make a mix first to steer the vocals"
                  : `Tap to toggle ${label}`
              }
              onClick={() => toggleBus(bus)}
            >
              {label}
            </button>
          );
        })}
      </div>
      <form aria-label="command" onSubmit={onSubmit}>
        <input
          placeholder="Try: drop everything but the beat"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit">Go</button>
      </form>
      <p className={styles.status} role="status">
        {status}
      </p>
    </div>
  );
}

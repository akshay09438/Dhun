import { useEffect, useRef, useState } from "react";
import { LivePlayer } from "../../lib/liveAudio";
import {
  postLiveCommand,
  getLiveContext,
  type LiveContextDTO,
} from "../../lib/api";
import { applyOp, type BusState, type BusName } from "../../lib/liveSchedule";
import styles from "./LiveMix.module.css";

const BUSES: BusName[] = ["drums", "bass", "other"];

export default function LiveMix({
  song1Id,
  song2Id,
}: {
  song1Id: string;
  song2Id: string;
}) {
  const playerRef = useRef<LivePlayer | null>(null);
  const ctxRef = useRef<LiveContextDTO>({ bpm: 120, downbeats: [] });
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [busState, setBusState] = useState<BusState>({
    drums: true,
    bass: true,
    other: true,
  });
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");

  useEffect(() => {
    // Guard: environments without Web Audio support (or a test DOM) shouldn't
    // crash the whole page — live mode just stays not-ready.
    let p: LivePlayer;
    try {
      p = new LivePlayer();
    } catch {
      return;
    }
    playerRef.current = p;
    Promise.all([p.load(song1Id, BUSES), getLiveContext(song1Id)]).then(
      ([, ctx]) => {
        ctxRef.current = ctx;
        setReady(true);
      },
    );
    return () => p.dispose();
  }, [song1Id]);

  function togglePlay() {
    const p = playerRef.current!;
    if (playing) {
      p.pause();
      setPlaying(false);
    } else {
      p.play();
      setPlaying(true);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    const op = await postLiveCommand(song1Id, song2Id, text);
    setStatus(op.say);
    if (op.op === "mute" || op.op === "unmute") {
      playerRef.current!.schedule(op, ctxRef.current);
      setBusState((s) => applyOp(s, op));
    }
    setText("");
  }

  return (
    <div className={styles.live}>
      <button onClick={togglePlay} disabled={!ready}>
        {playing ? "Pause" : "Play"}
      </button>
      <div className={styles.buses}>
        {BUSES.map((b) => (
          <span
            key={b}
            data-testid={`bus-${b}`}
            data-on={busState[b]}
            className={busState[b] ? styles.on : styles.off}
          >
            {b}
          </span>
        ))}
      </div>
      <form aria-label="command" onSubmit={onSubmit}>
        <input
          placeholder="Try: take the bass out"
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

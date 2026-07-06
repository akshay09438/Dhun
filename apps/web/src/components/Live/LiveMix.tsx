import { useEffect, useRef, useState } from "react";
import { LivePlayer } from "../../lib/liveAudio";
import {
  postLiveCommand,
  getLiveContext,
  getSuggestions,
  type LiveContextDTO,
  type LiveOpDTO,
  type SectionSuggestionsDTO,
} from "../../lib/api";
import {
  applyOp,
  currentChips,
  type BusState,
  type BusName,
  type Chip,
} from "../../lib/liveSchedule";
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
  const [sections, setSections] = useState<SectionSuggestionsDTO[]>([]);
  const [chips, setChips] = useState<Chip[]>([]);

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

  // Load the per-section suggestion chips for the current mix (once per take).
  useEffect(() => {
    setSections([]);
    setChips([]);
    if (!mixId) return;
    getSuggestions(mixId)
      .then(setSections)
      .catch(() => setSections([])); // chips are optional — parts + typed commands still work
  }, [mixId]);

  // While playing, follow the playhead and show the current section's chips.
  useEffect(() => {
    if (!playing || sections.length === 0) {
      setChips([]);
      return;
    }
    const id = setInterval(() => {
      const t = playerRef.current?.songTime() ?? 0;
      setChips(currentChips(sections, t));
    }, 250);
    return () => clearInterval(id);
  }, [playing, sections]);

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

  /** Apply an op to the audio + the on/off state (shared by taps, chips, typed commands). */
  function runOp(op: LiveOpDTO) {
    if (op.op === "mute" || op.op === "unmute" || op.op === "fade") {
      playerRef.current?.schedule(op, ctxRef.current);
      setBusState((s) => applyOp(s, op));
    }
  }

  function tapChip(chip: Chip) {
    const op: LiveOpDTO = {
      op: chip.op as LiveOpDTO["op"],
      target: chip.targets.length === 1 ? chip.targets[0] : null,
      targets: chip.targets,
      when: "next_bar",
      say: "",
      reason: null,
    };
    runOp(op);
    setStatus(`${chip.text.toLowerCase()} — on the next bar`);
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
      {chips.length > 0 && (
        <div className={styles.suggestions} aria-label="suggestions">
          <span className={styles.suggestLabel}>Try:</span>
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
      )}
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

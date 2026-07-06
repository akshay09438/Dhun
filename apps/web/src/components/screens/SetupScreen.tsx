import { useEffect, useRef, useState } from "react";
import { getLibrary, type LibrarySongDTO } from "../../lib/api";
import styles from "./SetupScreen.module.css";

/** MVP setup: users pick two songs from the curated catalog (no uploads).
 *  Every catalog song is pre-analyzed and tempo-verified, so any pair blends. */
export default function SetupScreen({
  pick1,
  pick2,
  onPick1,
  onPick2,
  canMix,
  onMixIt,
}: {
  pick1: LibrarySongDTO | null;
  pick2: LibrarySongDTO | null;
  onPick1: (s: LibrarySongDTO | null) => void;
  onPick2: (s: LibrarySongDTO | null) => void;
  canMix: boolean;
  onMixIt: () => void;
}) {
  const [library, setLibrary] = useState<LibrarySongDTO[]>([]);
  const [libError, setLibError] = useState(false);
  const [open, setOpen] = useState<1 | 2 | null>(null);
  const consoleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getLibrary()
      .then(setLibrary)
      .catch(() => setLibError(true));
  }, []);

  // Each slot only offers songs for its role: Song 1 = beats, Song 2 = vocals.
  const beats = library.filter((s) => s.role_hint === "beat");
  const vocals = library.filter((s) => s.role_hint === "vocals");

  // Any click outside the open dropdown closes it.
  useEffect(() => {
    if (open === null) return;
    const close = (e: MouseEvent) => {
      if (!consoleRef.current?.contains(e.target as Node)) setOpen(null);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  function choose(slot: 1 | 2, song: LibrarySongDTO) {
    (slot === 1 ? onPick1 : onPick2)(song);
    setOpen(null);
  }

  return (
    <>
      <div className="console" ref={consoleRef}>
        <p className="kicker">New mix</p>
        <h1 className="title">Pick your two songs</h1>

        <SongSlot
          n={1}
          picked={pick1}
          placeholder="Song One"
          role="→ its beat"
          library={beats}
          libError={libError}
          open={open === 1}
          onToggle={() => setOpen(open === 1 ? null : 1)}
          onChoose={(s) => choose(1, s)}
        />
        <SongSlot
          n={2}
          picked={pick2}
          placeholder="Song Two"
          role="→ its vocals"
          library={vocals}
          libError={libError}
          open={open === 2}
          onToggle={() => setOpen(open === 2 ? null : 2)}
          onChoose={(s) => choose(2, s)}
        />

        <button className="btnPrimary" disabled={!canMix} onClick={onMixIt}>
          Mix it&nbsp;&nbsp;▸
        </button>
      </div>

      <div className="stage">
        <div className={styles.tiles}>
          <Tile label={pick1 ? pick1.original_name : "SONG 1"} />
          <span className={styles.tilePlus}>＋</span>
          <Tile label={pick2 ? pick2.original_name : "SONG 2"} />
        </div>
        <p className={styles.tagline}>
          Two songs in.
          <br />
          One mix out — arranged like a DJ.
        </p>
      </div>
    </>
  );
}

function SongSlot({
  n,
  picked,
  placeholder,
  role,
  library,
  libError,
  open,
  onToggle,
  onChoose,
}: {
  n: number;
  picked: LibrarySongDTO | null;
  placeholder: string;
  role: string;
  library: LibrarySongDTO[];
  libError: boolean;
  open: boolean;
  onToggle: () => void;
  onChoose: (s: LibrarySongDTO) => void;
}) {
  return (
    <div className={styles.slotWrap}>
      <button
        type="button"
        className={styles.upload}
        data-testid={`song-slot-${n}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={onToggle}
      >
        <span className={styles.plus}>{picked ? "↺" : "▾"}</span>
        <span className={styles.badge}>{n}</span>
        <span className={styles.songName} title={picked?.original_name}>
          {picked ? picked.original_name : placeholder}
        </span>
        <span className={styles.role}>{role}</span>
      </button>

      {open && (
        <div
          className={styles.dropdown}
          role="listbox"
          aria-label={`Choose ${placeholder}`}
        >
          {libError && (
            <div className={styles.dropNote}>
              Couldn&rsquo;t load the songs. Is the app&rsquo;s backend running?
            </div>
          )}
          {!libError && library.length === 0 && (
            <div className={styles.dropNote}>No songs in the library yet.</div>
          )}
          {library.map((s) => (
            <button
              key={s.id}
              type="button"
              role="option"
              aria-selected={picked?.id === s.id}
              className={
                picked?.id === s.id
                  ? `${styles.dropItem} ${styles.dropItemActive}`
                  : styles.dropItem
              }
              title={s.original_name}
              onClick={() => onChoose(s)}
            >
              {s.original_name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Tile({ label }: { label: string }) {
  return (
    <div className={styles.tile} title={label}>
      {label}
    </div>
  );
}

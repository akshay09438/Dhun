import { useEffect, useRef, useState } from "react";
import { getLibrary, type LibrarySongDTO } from "../../lib/api";
import { MAX_MIXES_PER_SET, type SetPick } from "../../types";
import styles from "./SetupScreen.module.css";

/** A set being composed: either slot may still be empty while the user picks. */
type SetDraft = {
  beat: LibrarySongDTO | null;
  vocal: LibrarySongDTO | null;
  rule: number; // 1 = simple, 3 = chop & repeat, 4 = echo
};

// The set path defaults every member to rule 1 (Simple); single mixes get their rule auto-assigned by
// the shuffler on the Play screen. The manual per-song rule picker was removed when rule choice went
// automatic (2026-08-07).
const emptyDraft = (): SetDraft => ({ beat: null, vocal: null, rule: 1 });
const isComplete = (d: SetDraft): d is SetPick =>
  Boolean(d.beat) && Boolean(d.vocal);

/** MVP setup: users pick two songs from the curated catalog (no uploads), and may optionally
 *  stack MORE mixes (up to MAX_MIXES_PER_SET) to play back-to-back as one continuous set. Every catalog
 *  song is pre-analyzed and tempo-verified, so any pair blends. The console edits the active mix;
 *  the stage shows the running order. Single-mix stays the default, effortless path. */
export default function SetupScreen({
  onBuild,
}: {
  /** Fired when every set in the line-up is complete and the user commits. */
  onBuild: (sets: SetPick[]) => void;
}) {
  const [library, setLibrary] = useState<LibrarySongDTO[]>([]);
  const [libError, setLibError] = useState(false);
  const [sets, setSets] = useState<SetDraft[]>([emptyDraft()]);
  const [active, setActive] = useState(0);
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

  const activeSet = sets[active] ?? emptyDraft();
  const canAddSet = sets.length < MAX_MIXES_PER_SET && sets.every(isComplete);
  const canBuild = sets.length > 0 && sets.every(isComplete);

  function choose(slot: 1 | 2, song: LibrarySongDTO) {
    setSets((prev) =>
      prev.map((d, i) =>
        i === active ? { ...d, [slot === 1 ? "beat" : "vocal"]: song } : d,
      ),
    );
    setOpen(null);
  }

  function addSet() {
    if (!canAddSet) return;
    setSets((prev) => [...prev, emptyDraft()]);
    setActive(sets.length); // focus the newly added set
    setOpen(null);
  }

  function removeSet(i: number) {
    if (sets.length <= 1) return; // always keep at least one set
    setSets((prev) => prev.filter((_, idx) => idx !== i));
    setActive((a) => (i <= a ? Math.max(0, a - 1) : a));
    setOpen(null);
  }

  /** Swap mix `i` with the one before it; repeated taps bubble it up the running order. */
  function moveUp(i: number) {
    if (i <= 0) return;
    setSets((prev) => {
      const next = [...prev];
      [next[i - 1], next[i]] = [next[i], next[i - 1]];
      return next;
    });
    setActive((a) => (a === i ? i - 1 : a === i - 1 ? i : a));
  }

  function selectSet(i: number) {
    setActive(i);
    setOpen(null);
  }

  function build() {
    if (canBuild) onBuild(sets.filter(isComplete));
  }

  const multi = sets.length > 1;

  return (
    <>
      <div className="console" ref={consoleRef}>
        <p className="kicker">
          {multi
            ? `New set · ${sets.length} of ${MAX_MIXES_PER_SET}`
            : "New mix"}
        </p>
        <h1 className="title">
          {multi ? "Build your set" : "Pick your two songs"}
        </h1>

        <SongSlot
          n={1}
          picked={activeSet.beat}
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
          picked={activeSet.vocal}
          placeholder="Song Two"
          role="→ its vocals"
          library={vocals}
          libError={libError}
          open={open === 2}
          onToggle={() => setOpen(open === 2 ? null : 2)}
          onChoose={(s) => choose(2, s)}
        />

        {sets.length < MAX_MIXES_PER_SET && (
          <button
            type="button"
            className={styles.addSet}
            data-testid="add-set"
            disabled={!canAddSet}
            onClick={addSet}
            title={
              canAddSet
                ? "Add another mix to play back-to-back"
                : "Finish this mix first"
            }
          >
            ＋ Add another set{" "}
            <span className={styles.addSetHint}>optional</span>
          </button>
        )}

        <button
          className="btnPrimary"
          disabled={!canBuild}
          onClick={build}
          style={{ marginTop: "auto" }}
        >
          {multi ? "Build the set" : "Mix it"}&nbsp;&nbsp;▸
        </button>
        <p className={styles.setNote}>
          Sets can only be added here — not once the mix is playing.
        </p>
      </div>

      <div className="stage">
        {multi ? (
          <>
            <div className={styles.roHead}>Running order</div>
            <div className={styles.ro} data-testid="running-order">
              {sets.map((d, i) => (
                <SetCard
                  key={i}
                  n={i + 1}
                  draft={d}
                  activeCard={i === active}
                  canRemove={sets.length > 1}
                  canMoveUp={i > 0}
                  onSelect={() => selectSet(i)}
                  onRemove={() => removeSet(i)}
                  onMoveUp={() => moveUp(i)}
                />
              ))}
            </div>
            <p className={styles.roFoot}>
              Played back-to-back as one continuous, beat-matched mix.
            </p>
          </>
        ) : (
          <>
            <div className={styles.tiles}>
              <Tile
                label={activeSet.beat ? activeSet.beat.original_name : "SONG 1"}
              />
              <span className={styles.tilePlus}>＋</span>
              <Tile
                label={
                  activeSet.vocal ? activeSet.vocal.original_name : "SONG 2"
                }
              />
            </div>
            <p className={styles.tagline}>
              Two songs in.
              <br />
              One mix out — arranged like a DJ.
            </p>
          </>
        )}
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

/** One row in the stage running order. Click to edit it in the console; ✕ to remove; ↑ to move it up. */
function SetCard({
  n,
  draft,
  activeCard,
  canRemove,
  canMoveUp,
  onSelect,
  onRemove,
  onMoveUp,
}: {
  n: number;
  draft: SetDraft;
  activeCard: boolean;
  canRemove: boolean;
  canMoveUp: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onMoveUp: () => void;
}) {
  const label = isComplete(draft)
    ? `${draft.beat.original_name} × ${draft.vocal.original_name}`
    : draft.beat
      ? `${draft.beat.original_name} × …`
      : "Pick two songs…";
  return (
    <div
      className={
        activeCard
          ? `${styles.setCard} ${styles.setCardActive}`
          : styles.setCard
      }
      data-testid={`set-card-${n}`}
    >
      <button
        type="button"
        className={styles.setSelect}
        onClick={onSelect}
        aria-current={activeCard}
        title="Edit this set"
      >
        <span className={styles.setBadge}>{n}</span>
        <span className={styles.setName} title={label}>
          {label}
        </span>
      </button>
      <div className={styles.setIcons}>
        <button
          type="button"
          className={styles.setIc}
          disabled={!canMoveUp}
          onClick={onMoveUp}
          aria-label={`Move set ${n} up`}
          title="Move up"
        >
          ↑
        </button>
        <button
          type="button"
          className={`${styles.setIc} ${styles.setIcX}`}
          disabled={!canRemove}
          data-testid={`remove-set-${n}`}
          onClick={onRemove}
          aria-label={`Remove set ${n}`}
          title="Remove this set"
        >
          ✕
        </button>
      </div>
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

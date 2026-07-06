export type BusName = "drums" | "bass" | "other" | "vocals";
export type BusState = Record<BusName, boolean>;

export function barSeconds(bpm: number): number {
  return (60 / bpm) * 4;
}

/** The first downbeat strictly after songTime; if none, round up to the next bar on the bpm grid. */
export function nextBarTime(
  downbeats: number[],
  songTime: number,
  bpm: number,
): number {
  const next = downbeats.find((d) => d > songTime + 1e-6);
  if (next !== undefined) return next;
  const bar = barSeconds(bpm);
  return Math.ceil((songTime + 1e-6) / bar) * bar;
}

export type OpLike = { op: string; target?: string | null; targets?: string[] };

/** The buses an op affects: `targets` when present, else the single `target`. */
export function busesOf(op: OpLike): BusName[] {
  const raw =
    op.targets && op.targets.length ? op.targets : op.target ? [op.target] : [];
  return raw.filter(
    (b): b is BusName =>
      b === "drums" || b === "bass" || b === "other" || b === "vocals",
  );
}

export function applyOp(state: BusState, op: OpLike): BusState {
  if (op.op !== "mute" && op.op !== "unmute" && op.op !== "fade") return state;
  const on = op.op === "unmute"; // mute and fade both settle a bus to off
  const next = { ...state };
  for (const b of busesOf(op)) next[b] = on;
  return next;
}

export function rampTarget(op: { op: string }): number {
  return op.op === "unmute" ? 1 : 0;
}

export type Chip = { text: string; op: string; targets: string[] };
export type Section = {
  start: number;
  end: number;
  label: string;
  chips: Chip[];
};

/** The section the playhead is in: the last section whose start <= songTime (sections are
 *  sorted by start). Undefined when there are no sections. */
export function currentSection(
  sections: Section[],
  songTime: number,
): Section | undefined {
  let cur: Section | undefined;
  for (const s of sections) {
    if (s.start <= songTime + 1e-6) cur = s;
    else break;
  }
  return cur;
}

/** The chips for the section the playhead is in. Empty when there are no sections. */
export function currentChips(sections: Section[], songTime: number): Chip[] {
  return currentSection(sections, songTime)?.chips ?? [];
}

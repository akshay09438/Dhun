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
  if (op.op !== "mute" && op.op !== "unmute") return state;
  const next = { ...state };
  for (const b of busesOf(op)) next[b] = op.op === "unmute";
  return next;
}

export function rampTarget(op: { op: string }): number {
  return op.op === "unmute" ? 1 : 0;
}

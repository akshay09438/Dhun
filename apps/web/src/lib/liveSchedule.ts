export type BusName = "drums" | "bass" | "other";
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

export function applyOp(
  state: BusState,
  op: { op: string; target: string | null },
): BusState {
  if (
    (op.op !== "mute" && op.op !== "unmute") ||
    !op.target ||
    !(op.target in state)
  )
    return state;
  return { ...state, [op.target as BusName]: op.op === "unmute" };
}

export function rampTarget(op: { op: string }): number {
  return op.op === "unmute" ? 1 : 0;
}

import type { LibrarySongDTO } from "./lib/api";

/** The four sequential screens of the app flow. */
export type Screen = "setup" | "generating" | "play" | "export";

/** One mix = a beat song + a vocal song. A SET is an ordered line-up of 1..MAX_MIXES_PER_SET of these,
 *  played back-to-back as one continuous, beat-matched piece. Each mix's rule is auto-assigned. */
export type SetPick = {
  beat: LibrarySongDTO;
  vocal: LibrarySongDTO;
  rule: number; // the set path's fallback rule; defaults to 1 (Simple). Ignored when the set is
  //              auto-ruled (user_id + set_index) — the manual per-song picker was removed.
};

/** How many mixes one continuous SET may hold. The single dial for the reach/cost trade — bigger sets
 *  mean longer renders and larger WAVs. Mirrors the backend set_route.MAX_MIXES_PER_SET. */
export const MAX_MIXES_PER_SET = 5;

/** How many generations (auto-ruled takes) a single mix session may produce — the "sitting" cap.
 *  The one place this number lives; the Play screen's "another take" stops when it's reached. */
export const MAX_GENERATIONS_PER_SESSION = 5;

/** The three live mixing rules, for display. Rule 2 is spec-only and never assigned. Mirrors the
 *  backend rule_shuffle.RULES / MixPlan.rule. */
export const RULE_LABELS: Record<number, string> = {
  1: "Simple",
  3: "Chop & repeat",
  4: "Echo",
};

/** A user-facing label for a mix's rule (empty string when unknown, e.g. an older plan). */
export function ruleLabel(rule?: number): string {
  return rule ? (RULE_LABELS[rule] ?? "") : "";
}

/** One line in the Play screen's set line-up (read-only there — sets are chosen on Setup). */
export type PlayMember = {
  index: number; // 1-based position in the line-up
  beat: string; // the beat song's name
  vocal: string; // the vocal song's name
  rule?: number; // the mixing rule this mix was made with (for the auto-assigned style label)
  kept: boolean; // false when the pair was dropped (e.g. too far off-tempo)
  reason: string | null; // plain-language reason it was dropped (when kept is false)
  seamAt: number | null; // seconds into the set where this member starts (null = the opening set)
};

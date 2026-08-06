import type { LibrarySongDTO } from "./lib/api";

/** The four sequential screens of the app flow. */
export type Screen = "setup" | "generating" | "play" | "export";

/** One set = a beat song + a vocal song. A session is 1 or 2 of these (V1 caps at two),
 *  played back-to-back as one continuous, beat-matched mix. */
export type SetPick = {
  beat: LibrarySongDTO;
  vocal: LibrarySongDTO;
  rule: number; // which mixing rule this song uses: 1 = simple, 3 = chop & repeat, 4 = echo
};

/** How many sets a single session may hold. Deliberately small: keeps render time and the
 *  finished set-WAV's file size down for V1. */
export const MAX_SETS = 2;

/** One line in the Play screen's set line-up (read-only there — sets are chosen on Setup). */
export type PlayMember = {
  index: number; // 1-based position in the line-up
  beat: string; // the beat song's name
  vocal: string; // the vocal song's name
  kept: boolean; // false when the pair was dropped (e.g. too far off-tempo)
  reason: string | null; // plain-language reason it was dropped (when kept is false)
  seamAt: number | null; // seconds into the set where this member starts (null = the opening set)
};

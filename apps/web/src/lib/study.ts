import {
  analyzeSong,
  makeMix,
  splitSong,
  type MixDTO,
  type PollOpts,
} from "./api";

/** The honest steps of the "Studying your songs" wait, in order. */
export type StudyStage =
  "uploading" | "splitting" | "analyzing" | "planning" | "done";

/** The step list the studying screen renders (drives the checklist). */
export const STUDY_STEPS: { stage: StudyStage; label: string }[] = [
  { stage: "uploading", label: "Uploading your two songs" },
  { stage: "splitting", label: "Splitting the vocals, drums & bass" },
  { stage: "analyzing", label: "Finding the beat, key & structure" },
  { stage: "planning", label: "Planning your arrangement" },
];

/**
 * Prepare both songs and produce a mix, hands-free — the one-click flow.
 *
 * Order is load-bearing: analysis reads the *split* vocal stem to find where the
 * singer sings, so every song is SPLIT before it is ANALYZED (otherwise the read
 * is weak and the planner plays overly safe). The two songs are prepared in
 * parallel — they're independent cloud jobs and don't load the local machine.
 *
 * `onStage` is called as each phase begins so the UI can show an honest
 * checklist. The caller owns the "uploading" phase (before song ids exist).
 */
export async function studyAndMix(
  song1Id: string,
  song2Id: string,
  onStage: (s: StudyStage) => void,
  prompt = "",
  opts: PollOpts = {},
): Promise<MixDTO> {
  onStage("splitting");
  await Promise.all([splitSong(song1Id, opts), splitSong(song2Id, opts)]);

  onStage("analyzing");
  await Promise.all([analyzeSong(song1Id, opts), analyzeSong(song2Id, opts)]);

  onStage("planning");
  const mix = await makeMix(song1Id, song2Id, prompt, 1, opts);

  onStage("done");
  return mix;
}

import {
  analyzeSong,
  makeMix,
  makeSet,
  splitSong,
  type MixDTO,
  type PollOpts,
  type SetDTO,
} from "./api";
import type { SetPick } from "../types";

/** The honest steps of the "Studying your songs" wait, in order. */
export type StudyStage =
  "uploading" | "splitting" | "analyzing" | "planning" | "done";

/** The step list the studying screen renders (drives the checklist). */
export const STUDY_STEPS: { stage: StudyStage; label: string }[] = [
  { stage: "uploading", label: "Loading your two songs" },
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

/**
 * Prepare every song in a 1–2 set line-up and join them into one continuous set.
 *
 * Same honest checklist as `studyAndMix` (catalog songs are already split/analyzed, so those
 * steps are instant), then the set builder renders each pair and joins them on the beat. The
 * "planning" step covers the render + join. Returns the finished set (with its per-set line-up).
 */
export async function studyAndBuildSet(
  sets: SetPick[],
  onStage: (s: StudyStage) => void,
  opts: PollOpts = {},
  bestParts = false,
): Promise<SetDTO> {
  const ids = Array.from(new Set(sets.flatMap((s) => [s.beat.id, s.vocal.id])));

  onStage("splitting");
  await Promise.all(ids.map((id) => splitSong(id, opts)));

  onStage("analyzing");
  await Promise.all(ids.map((id) => analyzeSong(id, opts)));

  onStage("planning");
  const set = await makeSet(
    sets.map((s) => ({ song1_id: s.beat.id, song2_id: s.vocal.id })),
    opts,
    bestParts,
  );

  onStage("done");
  return set;
}

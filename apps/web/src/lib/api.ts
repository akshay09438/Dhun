export const API_BASE = "http://localhost:8000";

/** How to wait on a start-then-poll job. Overridable so tests can poll fast. */
export type PollOpts = { pollMs?: number; maxTries?: number };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export type SongDTO = {
  id: string;
  original_name: string;
  url: string;
  status: string;
};

/** Upload two songs to be cleaned; returns the two playable records. */
export async function uploadSongs(
  file1: File,
  file2: File,
): Promise<{ songs: SongDTO[] }> {
  const body = new FormData();
  body.append("song1", file1);
  body.append("song2", file2);

  const res = await fetch(`${API_BASE}/songs`, { method: "POST", body });
  if (!res.ok) {
    const msg = await res.json().catch(() => ({ detail: "Upload failed." }));
    throw new Error(msg.detail ?? "Upload failed.");
  }
  return res.json();
}

export type StemSetDTO = {
  song_id: string;
  status: string; // "processing" | "ready" | "error" | "idle"
  stems: Record<string, string>;
};

/** Start splitting a song in the cloud. Returns immediately (status "processing"). */
export async function startSplit(songId: string): Promise<StemSetDTO> {
  const res = await fetch(`${API_BASE}/songs/${songId}/stems`, {
    method: "POST",
  });
  if (!res.ok) {
    const msg = await res.json().catch(() => ({ detail: "Splitting failed." }));
    throw new Error(msg.detail ?? "Splitting failed.");
  }
  return res.json();
}

/** Check how the split is going: processing / ready (with URLs) / error. */
export async function getStemStatus(songId: string): Promise<StemSetDTO> {
  const res = await fetch(`${API_BASE}/songs/${songId}/stems`);
  if (!res.ok) {
    throw new Error("Could not check the split status.");
  }
  return res.json();
}

/** Split a song and wait until its parts are ready (start + poll). */
export async function splitSong(
  songId: string,
  { pollMs = 3000, maxTries = 80 }: PollOpts = {},
): Promise<StemSetDTO> {
  const started = await startSplit(songId);
  if (started.status === "ready") return started;
  for (let i = 0; i < maxTries; i++) {
    const s = await getStemStatus(songId);
    if (s.status === "ready") return s;
    if (s.status === "error")
      throw new Error("The split failed. Please try again.");
    await sleep(pollMs);
  }
  throw new Error("The split is taking too long. Please try again.");
}

export type SectionDTO = { start: number; end: number; label: string };

export type TrackAnalysisDTO = {
  song_id: string;
  status: string; // "processing" | "ready" | "error" | "idle"
  bpm: number | null;
  key: {
    camelot: string;
    tonic: string;
    mode: string;
    confidence: number;
  } | null;
  sections: SectionDTO[];
};

/** Start analyzing a song (beat, key, structure). Returns immediately. */
export async function startAnalysis(songId: string): Promise<TrackAnalysisDTO> {
  const res = await fetch(`${API_BASE}/songs/${songId}/analysis`, {
    method: "POST",
  });
  if (!res.ok) {
    const msg = await res.json().catch(() => ({ detail: "Analysis failed." }));
    throw new Error(msg.detail ?? "Analysis failed.");
  }
  return res.json();
}

/** Check how the analysis is going: processing / ready (with data) / error. */
export async function getAnalysisStatus(
  songId: string,
): Promise<TrackAnalysisDTO> {
  const res = await fetch(`${API_BASE}/songs/${songId}/analysis`);
  if (!res.ok) {
    throw new Error("Could not check the analysis status.");
  }
  return res.json();
}

/** Analyze a song and wait until the beat/key/structure read is ready. */
export async function analyzeSong(
  songId: string,
  { pollMs = 3000, maxTries = 100 }: PollOpts = {},
): Promise<TrackAnalysisDTO> {
  const started = await startAnalysis(songId);
  if (started.status === "ready") return started;
  for (let i = 0; i < maxTries; i++) {
    const s = await getAnalysisStatus(songId);
    if (s.status === "ready") return s;
    if (s.status === "error")
      throw new Error("The analysis failed. Please try again.");
    await sleep(pollMs);
  }
  throw new Error("The analysis is taking too long. Please try again.");
}

export type PlacementDTO = {
  anchor: number;
  vocal_src: [number, number];
  beat_breath: boolean;
  fx: string | null; // e.g. "sweep_in"
};

export type MixPlanDTO = {
  master_bpm: number;
  vocal_stretch: number;
  anchor: number;
  beat_breath: boolean;
  placements: PlacementDTO[];
  s1_vocal_regions: [number, number][]; // spans where Song 1's own vocal answers
  take: number;
  notes: string;
  source: string; // "ai" | "rules"
};

export type MixDTO = {
  mix_id: string;
  status: string; // "processing" | "ready" | "error" | "idle"
  url: string | null;
  plan: MixPlanDTO | null;
  message: string | null;
};

/** Start making a mix of Song 1's beat + Song 2's vocal. Returns immediately. */
export async function startMix(
  song1Id: string,
  song2Id: string,
  prompt = "",
  take = 1,
): Promise<MixDTO> {
  const res = await fetch(`${API_BASE}/mix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      song1_id: song1Id,
      song2_id: song2Id,
      prompt,
      take,
    }),
  });
  if (!res.ok) {
    // 409 carries a plain-language reason (e.g. "Song 1 hasn't been analyzed yet.")
    const msg = await res
      .json()
      .catch(() => ({ detail: "Couldn't start the mix." }));
    throw new Error(msg.detail ?? "Couldn't start the mix.");
  }
  return res.json();
}

/** Check how the mix is going: processing / ready (with plan + url) / error. */
export async function getMixStatus(mixId: string): Promise<MixDTO> {
  const res = await fetch(`${API_BASE}/mix/${mixId}`);
  if (!res.ok) {
    throw new Error("Could not check the mix status.");
  }
  return res.json();
}

/** Make a mix and wait until it's rendered (start + poll). */
export async function makeMix(
  song1Id: string,
  song2Id: string,
  prompt = "",
  take = 1,
  { pollMs = 3000, maxTries = 80 }: PollOpts = {},
): Promise<MixDTO> {
  const started = await startMix(song1Id, song2Id, prompt, take);
  if (started.status === "ready") return started;
  for (let i = 0; i < maxTries; i++) {
    const s = await getMixStatus(started.mix_id);
    if (s.status === "ready") return s;
    if (s.status === "error")
      throw new Error(s.message ?? "This pair couldn't be mixed. Try another.");
    await sleep(pollMs);
  }
  throw new Error("The mix is taking too long. Please try again.");
}

export type LiveOpDTO = {
  op: "mute" | "unmute" | "decline" | "fade";
  target: string | null;
  targets?: string[];
  when: string;
  say: string;
  reason: string | null;
};

export type LiveChipDTO = { text: string; op: string; targets: string[] };
export type SectionSuggestionsDTO = {
  start: number;
  end: number;
  label: string;
  chips: LiveChipDTO[];
};

export type LiveContextDTO = { bpm: number | null; downbeats: number[] };

/** Per-section suggestion chips for a finished mix (one cached AI call server-side). */
export async function getSuggestions(
  mixId: string,
): Promise<SectionSuggestionsDTO[]> {
  const res = await fetch(`${API_BASE}/live/suggestions/${mixId}`);
  if (!res.ok) throw new Error("Couldn't load suggestions.");
  const data = await res.json();
  return data.sections ?? [];
}

/** Turn a typed steering command into a structured op the player runs on the beat. */
export async function postLiveCommand(
  song1Id: string,
  song2Id: string,
  text: string,
): Promise<LiveOpDTO> {
  const res = await fetch(`${API_BASE}/live/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ song1_id: song1Id, song2_id: song2Id, text }),
  });
  if (!res.ok) throw new Error("Couldn't run that command.");
  return res.json();
}

/** The beatgrid the live player schedules on (Song 1's tempo + downbeats). */
export async function getLiveContext(song1Id: string): Promise<LiveContextDTO> {
  const res = await fetch(`${API_BASE}/live/context/${song1Id}`);
  if (!res.ok) throw new Error("Couldn't load the beat map.");
  return res.json();
}

const VOCAL_BUS_POLL_MS = 1500;

/** Fetch the arranged-vocal-bus WAV for a mix, polling past 202 while it renders. */
export async function fetchVocalBus(mixId: string): Promise<ArrayBuffer> {
  for (let i = 0; i < 80; i++) {
    const res = await fetch(`${API_BASE}/live/vocal-bus/${mixId}`);
    if (res.status === 200) return res.arrayBuffer();
    if (res.status === 202) {
      await new Promise((r) => setTimeout(r, VOCAL_BUS_POLL_MS));
      continue;
    }
    throw new Error("Couldn't prepare the live vocals.");
  }
  throw new Error("Preparing the live vocals took too long.");
}

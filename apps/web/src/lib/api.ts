export const API_BASE = "http://localhost:8000";

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

export type PlacementDTO = {
  anchor: number;
  vocal_src: [number, number];
  beat_breath: boolean;
};

export type MixPlanDTO = {
  master_bpm: number;
  vocal_stretch: number;
  anchor: number;
  beat_breath: boolean;
  placements: PlacementDTO[];
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

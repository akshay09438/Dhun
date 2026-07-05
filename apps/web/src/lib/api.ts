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

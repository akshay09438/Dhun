// Where the backend lives. In local dev (Vite on :5173) default to the :8000 API.
// In a production build (served BY the backend, e.g. through a tunnel) default to
// same-origin ("") so one host serves the UI and the API — no CORS, keys never
// cross-origin. Override with VITE_API_BASE when the two are hosted separately.
const _envBase = (import.meta.env as Record<string, string | undefined>)
  .VITE_API_BASE;
export const API_BASE =
  _envBase ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

/** How to wait on a start-then-poll job. Overridable so tests can poll fast. */
export type PollOpts = { pollMs?: number; maxTries?: number };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Every request the app makes goes through here so it carries `X-PromptDJ-App`.
 *
 * The engine refuses POST/PUT/PATCH/DELETE without that header. CORS alone does not stop a
 * cross-origin request from EXECUTING - it only withholds the response - and a multipart POST is
 * CORS-safelisted, so it gets no preflight at all. A custom header cannot be set cross-origin
 * without a preflight, and that preflight is refused, so this one header is what stops any page
 * open in the browser from driving the API. See services/api/app/main.py.
 */
export function apiFetch(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers ?? {});
  headers.set("X-PromptDJ-App", "web");
  return fetch(input, { ...init, headers });
}

export type SongDTO = {
  id: string;
  original_name: string;
  url: string;
  status: string;
};

export type LibrarySongDTO = SongDTO & {
  role_hint?: string;
  language?: string;
  /** One of the curated menu songs. Uploads are never featured. */
  featured?: boolean;
  /** Added by a person with /add. Kept out of this console - it is their song. */
  uploaded?: boolean;
};

/** The curated song catalog (MVP: users pick from these instead of uploading). */
export async function getLibrary(): Promise<LibrarySongDTO[]> {
  const res = await apiFetch(`${API_BASE}/library`);
  if (!res.ok) throw new Error("Couldn't load the song library.");
  const data = await res.json();
  return data.songs ?? [];
}

/** Upload two songs to be cleaned; returns the two playable records. */
export async function uploadSongs(
  file1: File,
  file2: File,
): Promise<{ songs: SongDTO[] }> {
  const body = new FormData();
  body.append("song1", file1);
  body.append("song2", file2);

  const res = await apiFetch(`${API_BASE}/songs`, { method: "POST", body });
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
  const res = await apiFetch(`${API_BASE}/songs/${songId}/stems`, {
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
  const res = await apiFetch(`${API_BASE}/songs/${songId}/stems`);
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
  const res = await apiFetch(`${API_BASE}/songs/${songId}/analysis`, {
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
  const res = await apiFetch(`${API_BASE}/songs/${songId}/analysis`);
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
  rule?: number; // which mixing rule made this take: 1 = simple, 3 = chop & repeat, 4 = echo
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

/** Auto rule assignment: a stable per-browser id + 0-based generation index. When supplied, the backend
 *  deterministically picks the rule (rule_shuffle) and uses the generation as the cache slot. */
export type AutoRule = { userId: string; generation: number };

/** Which surface a mix was made from, so the ops dashboard can separate web activity from the
 *  Discord bot's. Attribution only — the backend records it and never lets it reach a cache id,
 *  so tagging requests cannot change a mix or re-render a cached one. */
const SOURCE = "web";

/** Start making a mix of Song 1's beat + Song 2's vocal. Returns immediately.
 *  Pass `auto` for the shuffler-assigned rule (single mixes); `take`/`rule` are used only without it. */
export async function startMix(
  song1Id: string,
  song2Id: string,
  prompt = "",
  take = 1,
  rule = 1, // 1 = simple mix, 3 = chop & repeat
  auto?: AutoRule,
): Promise<MixDTO> {
  const body = auto
    ? {
        song1_id: song1Id,
        song2_id: song2Id,
        prompt,
        user_id: auto.userId,
        generation: auto.generation,
        source: SOURCE,
      }
    : {
        song1_id: song1Id,
        song2_id: song2Id,
        prompt,
        take,
        rule,
        source: SOURCE,
      };
  const res = await apiFetch(`${API_BASE}/mix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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
  const res = await apiFetch(`${API_BASE}/mix/${mixId}`);
  if (!res.ok) {
    throw new Error("Could not check the mix status.");
  }
  return res.json();
}

/** Make a mix and wait until it's rendered (start + poll). Pass `auto` for the shuffler-assigned rule. */
export async function makeMix(
  song1Id: string,
  song2Id: string,
  prompt = "",
  take = 1,
  { pollMs = 3000, maxTries = 80 }: PollOpts = {},
  rule = 1, // 1 = simple mix, 3 = chop & repeat
  auto?: AutoRule,
): Promise<MixDTO> {
  const started = await startMix(song1Id, song2Id, prompt, take, rule, auto);
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

/** An AI-generated playful name for a mix, from the two song filenames.
 *  Cached server-side; falls back to a simple "A × B" if the AI is unavailable. */
export async function getMixName(
  song1Name: string,
  song2Name: string,
  prompt = "",
): Promise<string> {
  const res = await apiFetch(`${API_BASE}/mix/name`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      song1_name: song1Name,
      song2_name: song2Name,
      prompt,
    }),
  });
  if (!res.ok) throw new Error("Couldn't name the mix.");
  const data = await res.json();
  return data.name ?? "";
}

export type LiveOpDTO = {
  op: "mute" | "unmute" | "decline" | "fade" | "beat_up";
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
  const res = await apiFetch(`${API_BASE}/live/suggestions/${mixId}`);
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
  const res = await apiFetch(`${API_BASE}/live/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ song1_id: song1Id, song2_id: song2Id, text }),
  });
  if (!res.ok) throw new Error("Couldn't run that command.");
  return res.json();
}

/** The beatgrid the live player schedules on (Song 1's tempo + downbeats). */
export async function getLiveContext(song1Id: string): Promise<LiveContextDTO> {
  const res = await apiFetch(`${API_BASE}/live/context/${song1Id}`);
  if (!res.ok) throw new Error("Couldn't load the beat map.");
  return res.json();
}

// ---- Sets: a continuous mix of 1–2 two-song sets, joined on the beat (V1 caps at two) ----

export type SetMemberDTO = {
  index: number; // 1-based position in the line-up
  song1_id: string;
  song2_id: string;
  rule?: number; // the mixing rule this mix was made with (auto-assigned)
  kept: boolean; // false when declined (too far off-tempo, or the pair couldn't be mixed)
  seam_at: number | null; // seconds into the set where this member's crossfade begins
  reason: string | null; // plain-language reason it was dropped (when kept is false)
};

export type SetDTO = {
  set_id: string;
  status: string; // "processing" | "ready" | "error" | "idle"
  url: string | null;
  members: SetMemberDTO[];
  duration: number | null;
  message: string | null;
};

/** Auto rule assignment for a set: a stable per-browser id + the set's 0-based ordinal. When supplied,
 *  the backend assigns each mix's rule by its position in the set (rule_for_set). */
export type AutoSet = { userId: string; setIndex: number };

/** Start building a continuous set from an ordered list of pairs. Returns immediately.
 *  Pass `auto` to have each mix's rule auto-assigned by the shuffler; otherwise each pair's rule is used. */
export async function startSet(
  pairs: { song1_id: string; song2_id: string; rule?: number }[],
  auto?: AutoSet,
): Promise<SetDTO> {
  const body = auto
    ? {
        sets: pairs.map((p) => ({
          song1_id: p.song1_id,
          song2_id: p.song2_id,
        })),
        user_id: auto.userId,
        set_index: auto.setIndex,
        source: SOURCE,
      }
    : { sets: pairs, source: SOURCE };
  const res = await apiFetch(`${API_BASE}/set`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const msg = await res
      .json()
      .catch(() => ({ detail: "Couldn't start the set." }));
    throw new Error(msg.detail ?? "Couldn't start the set.");
  }
  return res.json();
}

/** Check how the set build is going: processing / ready (url + line-up) / error. */
export async function getSetStatus(setId: string): Promise<SetDTO> {
  const res = await apiFetch(`${API_BASE}/set/${setId}`);
  if (!res.ok) throw new Error("Could not check the set status.");
  return res.json();
}

/** Build a set and wait until it's rendered + joined (start + poll). Pass `auto` to auto-assign rules. */
export async function makeSet(
  pairs: { song1_id: string; song2_id: string; rule?: number }[],
  { pollMs = 3000, maxTries = 120 }: PollOpts = {},
  auto?: AutoSet,
): Promise<SetDTO> {
  const started = await startSet(pairs, auto);
  if (started.status === "ready") return started;
  for (let i = 0; i < maxTries; i++) {
    const s = await getSetStatus(started.set_id);
    if (s.status === "ready") return s;
    if (s.status === "error")
      throw new Error(
        s.message ?? "This set couldn't be built. Try other songs.",
      );
    await sleep(pollMs);
  }
  throw new Error("The set is taking too long. Please try again.");
}

// ============================================================================
// Internal OPS dashboard (developer-only, reached at #dev). Read-only.
// ============================================================================

/** One anomaly the engine flagged on a mix (already produced, but a degraded/unexpected condition). */
export type OpsAnomaly = {
  code: string;
  detail: string;
  action: string;
  severity: string; // "info" | "warn"
};

/** One recorded mix or set outcome, as the dashboard shows it. */
export type OpsEvent = {
  id: number;
  created_at: string;
  kind: string; // "mix" | "set"
  via: string; // "single" | "set" (a mix made inside a set)
  ref_id: string; // the mix_id / set_id (used to play it back)
  user_id: string | null; // a per-browser device tag on the web; a real account id on Discord
  source?: string | null; // "web" | "discord" | null (recorded before mixes were tagged)
  user_name?: string | null; // a Discord display name where we have one
  song1_name: string | null;
  song2_name: string | null;
  rule: number | null;
  rule_label: string | null;
  take: number | null;
  status: string; // "ok" | "failed"
  health: string; // "green" | "amber" | "red"
  fail_reason: string | null;
  anomalies: OpsAnomaly[];
  extra: Record<string, unknown> & { audio_url?: string };
};

export type OpsSummary = {
  total: number;
  failed: number;
  degraded: number;
  devices: number;
  today_total: number;
  today_failed: number;
  today_degraded: number;
  mixes: number;
  sets: number;
  /** Activity by surface. Keys are "web" | "discord" | "unknown" (rows made before the column existed). */
  by_source: Record<string, number>;
  people_by_source: Record<string, number>;
  /** Which clock the day/hour numbers are in — shown to the operator, never assumed. */
  report_tz: string;
};

export type OpsDevice = {
  user_id: string;
  total: number;
  failed: number;
  degraded: number;
  first_at: string;
  last_at: string;
  first_day: string;
  last_day: string;
  active_days: number; // distinct days this device made anything (>=2 = it came back)
  source: string; // "web" | "discord" | "unknown"
  user_name: string | null; // a Discord display name; null on the web (no login yet)
};

/** One catalog song's usage — the MUSIC view. */
export type OpsSong = {
  song_id: string;
  name: string;
  as_beat: number;
  as_vocal: number;
  used: number;
  failed: number;
  degraded: number;
  top_partner: string | null;
};

/** Activity over time — the WHEN view. Hours/weekdays are dense arrays (24 / 7). */
export type OpsTime = {
  by_hour: number[];
  by_weekday: number[]; // index 0 = Sunday
  by_day: { day: string; n: number; failed: number; degraded: number }[];
  days: number;
  report_tz: string;
};

/** What is actually breaking, most common first. */
export type OpsHealthReasons = {
  failures: { reason: string; n: number }[];
  degradations: { code: string; n: number }[];
};

/** One person's page. `found` is false for an id with no activity (an empty state, not an error). */
export type OpsPerson = {
  user_id: string;
  found: boolean;
  total: number;
  failed?: number;
  degraded?: number;
  sets?: number;
  first_at?: string;
  last_at?: string;
  first_day?: string;
  last_day?: string;
  active_days?: number;
  max_take?: number;
  avg_take?: number;
  source?: string;
  user_name?: string | null;
  by_hour?: number[];
  by_weekday?: number[];
  top_beats?: { name: string | null; n: number }[];
  top_vocals?: { name: string | null; n: number }[];
  sittings?: number;
  report_tz?: string;
};

/** Device-level retention (directional — counts persistent browsers, not verified people, until login). */
export type OpsRetention = {
  total_devices: number;
  returning_devices: number; // active on 2+ distinct days
  new_today: number;
  returning_today: number;
};

/** Error thrown when the dashboard API is locked (a token is required but missing/wrong). */
export class DashboardLockedError extends Error {}

const DASHBOARD_TOKEN_KEY = "promptdj_dashboard_token";

/** The dashboard API is open on localhost. When deployed it's gated by a shared token; if the
 *  operator has stored one, send it. (Never in a URL — always a header.) */
function adminHeaders(): Record<string, string> {
  try {
    const t = localStorage.getItem(DASHBOARD_TOKEN_KEY);
    return t ? { "X-Dashboard-Token": t } : {};
  } catch {
    return {};
  }
}

async function getAdmin<T>(path: string): Promise<T> {
  const res = await apiFetch(`${API_BASE}${path}`, { headers: adminHeaders() });
  if (res.status === 401) {
    throw new DashboardLockedError(
      "This dashboard is locked — an access token is required.",
    );
  }
  if (!res.ok) throw new Error("Couldn't load the dashboard data.");
  return res.json();
}

/** The health-strip numbers. */
export function getOpsSummary(): Promise<OpsSummary> {
  return getAdmin<OpsSummary>("/admin/summary");
}

/** A page of events, newest first. `total` is every matching event; page through with `offset`. */
export function getOpsEvents(
  opts: {
    limit?: number;
    offset?: number;
    userId?: string | null;
    kind?: string | null;
  } = {},
): Promise<{ events: OpsEvent[]; total: number }> {
  const q = new URLSearchParams();
  q.set("limit", String(opts.limit ?? 50));
  q.set("offset", String(opts.offset ?? 0));
  if (opts.userId) q.set("user_id", opts.userId);
  if (opts.kind) q.set("kind", opts.kind);
  return getAdmin(`/admin/events?${q.toString()}`);
}

/** The per-device rollup, busiest first. */
export function getOpsDevices(): Promise<OpsDevice[]> {
  return getAdmin<OpsDevice[]>("/admin/devices");
}

/** Device-level retention: how many devices are returning vs new. */
export function getOpsRetention(): Promise<OpsRetention> {
  return getAdmin<OpsRetention>("/admin/retention");
}

/** The MUSIC view: per-song usage as beat vs vocal, with failure counts and top partner. */
export function getOpsSongs(): Promise<OpsSong[]> {
  return getAdmin<OpsSong[]>("/admin/songs");
}

/** The WHEN view: by hour, by weekday, and a bounded day-by-day line. */
export function getOpsTime(days = 30): Promise<OpsTime> {
  return getAdmin<OpsTime>(`/admin/time?days=${days}`);
}

/** Ranked failure reasons and degradation codes. */
export function getOpsHealthReasons(): Promise<OpsHealthReasons> {
  return getAdmin<OpsHealthReasons>("/admin/health-reasons");
}

/** One person's page. Ids can contain odd characters, so encode before it hits the URL. */
export function getOpsPerson(userId: string): Promise<OpsPerson> {
  return getAdmin<OpsPerson>(`/admin/person/${encodeURIComponent(userId)}`);
}

const VOCAL_BUS_POLL_MS = 1500;

/** Fetch the arranged-vocal-bus WAV for a mix, polling past 202 while it renders. */
export async function fetchVocalBus(mixId: string): Promise<ArrayBuffer> {
  for (let i = 0; i < 80; i++) {
    const res = await apiFetch(`${API_BASE}/live/vocal-bus/${mixId}`);
    if (res.status === 200) return res.arrayBuffer();
    if (res.status === 202) {
      await new Promise((r) => setTimeout(r, VOCAL_BUS_POLL_MS));
      continue;
    }
    throw new Error("Couldn't prepare the live vocals.");
  }
  throw new Error("Preparing the live vocals took too long.");
}

// A stable, per-browser identity for the deterministic rule shuffler.
//
// V1 has no real accounts, but the auto-rule order must be STABLE per person (so a given user keeps
// getting the same rule for the same pair+generation — requirements R3/R5 of the shuffler). So we mint
// a random id once and persist it in localStorage. It is not PII and is only ever sent to /mix as the
// shuffle seed input; it never identifies the person.

const KEY = "promptdj_user_id";
const SET_KEY = "promptdj_set_index";
let cached: string | null = null;

function mint(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Older browsers: a good-enough unique id (only used to SEED the shuffle, never for security).
  return `u_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

/** This browser's stable shuffle id — created once, then reused for the life of the browser profile. */
export function getUserId(): string {
  if (cached) return cached;
  try {
    const existing = localStorage.getItem(KEY);
    if (existing) {
      cached = existing;
      return existing;
    }
    const id = mint();
    localStorage.setItem(KEY, id);
    cached = id;
    return id;
  } catch {
    // localStorage blocked (private mode / disabled): fall back to one stable id for this session so
    // the shuffle is at least consistent while the tab is open.
    cached = cached ?? mint();
    return cached;
  }
}

/** Return this user's next SET ordinal (0, 1, 2, …) and advance the stored counter. The ordinal seeds
 *  the set shuffler, so incrementing it per set is what makes a user's consecutive sets differ. Persisted
 *  across sittings so the sequence keeps moving; falls back to 0 if storage is blocked. */
export function takeNextSetIndex(): number {
  try {
    const cur = parseInt(localStorage.getItem(SET_KEY) ?? "0", 10) || 0;
    localStorage.setItem(SET_KEY, String(cur + 1));
    return cur;
  } catch {
    return 0;
  }
}

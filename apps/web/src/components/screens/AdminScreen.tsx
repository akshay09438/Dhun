import { useCallback, useEffect, useState } from "react";
import {
  API_BASE,
  DashboardLockedError,
  getOpsDevices,
  getOpsEvents,
  getOpsHealthReasons,
  getOpsPerson,
  getOpsRetention,
  getOpsSongs,
  getOpsSummary,
  getOpsTime,
  type OpsDevice,
  type OpsEvent,
  type OpsHealthReasons,
  type OpsPerson,
  type OpsRetention,
  type OpsSong,
  type OpsSummary,
  type OpsTime,
} from "../../lib/api";
import { HealthPanel, MusicPanel, PersonPanel, WhenPanel } from "./AdminPanels";
import styles from "./AdminScreen.module.css";

const PAGE = 50;

type View = "overview" | "people" | "music" | "when";

const TABS: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "people", label: "People" },
  { id: "music", label: "Music" },
  { id: "when", label: "When" },
];

/** The internal developer / operations dashboard (reached at #dev). Read-only.
 *
 *  Four tabs, each answering one operator question — Overview: is it healthy? People: who is
 *  using it? Music: what are they making? When: when do they use it? Clicking a person opens
 *  their own page (their songs, their hours, their history).
 *
 *  Deliberately plain, at the founder's request: numbers and simple bars, no charting library.
 *  This is an ops tool, not part of the user flow — it never changes or deletes anything. */
export function AdminScreen() {
  const [view, setView] = useState<View>("overview");
  const [summary, setSummary] = useState<OpsSummary | null>(null);
  const [events, setEvents] = useState<OpsEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [devices, setDevices] = useState<OpsDevice[]>([]);
  const [retention, setRetention] = useState<OpsRetention | null>(null);
  const [songs, setSongs] = useState<OpsSong[]>([]);
  const [time, setTime] = useState<OpsTime | null>(null);
  const [health, setHealth] = useState<OpsHealthReasons | null>(null);
  const [person, setPerson] = useState<OpsPerson | null>(null);
  const [deviceFilter, setDeviceFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [playing, setPlaying] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sum, ev, dev] = await Promise.all([
        getOpsSummary(),
        getOpsEvents({ limit: PAGE, offset: 0, userId: deviceFilter }),
        getOpsDevices(),
      ]);
      setSummary(sum);
      setEvents(ev.events);
      setTotal(ev.total);
      setDevices(dev);
      setLocked(false);
      // The rollups are supplementary: a failure fetching any of them must never break the core
      // failure-visibility feed, so they load separately and each degrades to "not shown".
      // Settled (not all) so one slow or broken rollup can't hide the others.
      const [ret, sng, tim, hea] = await Promise.allSettled([
        getOpsRetention(),
        getOpsSongs(),
        getOpsTime(),
        getOpsHealthReasons(),
      ]);
      setRetention(ret.status === "fulfilled" ? ret.value : null);
      setSongs(sng.status === "fulfilled" ? sng.value : []);
      setTime(tim.status === "fulfilled" ? tim.value : null);
      setHealth(hea.status === "fulfilled" ? hea.value : null);
    } catch (e) {
      if (e instanceof DashboardLockedError) setLocked(true);
      else
        setError(
          e instanceof Error ? e.message : "Couldn't load the dashboard.",
        );
    } finally {
      setLoading(false);
    }
  }, [deviceFilter]);

  /** Open one person's page. Their detail is fetched on demand — the People list only needs the
   *  rollup, so we don't pay for every person's history up front. */
  const openPerson = useCallback(async (userId: string) => {
    setPerson({ user_id: userId, found: false, total: 0 });
    try {
      setPerson(await getOpsPerson(userId));
    } catch {
      setPerson({ user_id: userId, found: false, total: 0 });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadMore = async () => {
    try {
      const ev = await getOpsEvents({
        limit: PAGE,
        offset: events.length,
        userId: deviceFilter,
      });
      setEvents((prev) => [...prev, ...ev.events]);
      setTotal(ev.total);
    } catch {
      /* a failed "load more" leaves what's already shown; the refresh button recovers */
    }
  };

  const saveToken = (token: string) => {
    try {
      localStorage.setItem("promptdj_dashboard_token", token.trim());
    } catch {
      /* storage blocked — nothing more we can do */
    }
    void load();
  };

  if (locked) return <TokenGate onSubmit={saveToken} />;

  return (
    <div className={styles.wrap}>
      <div className={styles.head}>
        <div>
          <p className={styles.kick}>Prompt-DJ · internal</p>
          <h1 className={styles.h1}>Ops dashboard</h1>
        </div>
        <button
          className={styles.refresh}
          onClick={() => void load()}
          data-testid="refresh"
        >
          ↻ Refresh
        </button>
      </div>

      <div className={styles.tiles} data-testid="health-strip">
        <Tile n={summary?.total} l="mixes & sets" />
        <Tile n={summary?.today_total} l="today" />
        <Tile
          n={summary?.failed}
          l="failed"
          tone={summary?.failed ? "red" : undefined}
        />
        <Tile
          n={summary?.degraded}
          l="degraded"
          tone={summary?.degraded ? "amber" : undefined}
        />
        <Tile n={peopleCount(summary)} l="people" />
      </div>

      {summary && <SourceStrip summary={summary} />}

      {/* One person's page takes over the body — it is a drill-down, not a fifth tab. */}
      {person ? (
        <>
          <div className={styles.toolbar}>
            <button
              className={styles.refresh}
              onClick={() => setPerson(null)}
              data-testid="person-back"
            >
              ← All people
            </button>
          </div>
          <PersonPanel
            person={person}
            onSeeMixes={() => {
              setDeviceFilter(person.user_id);
              setPerson(null);
              setView("overview");
            }}
          />
        </>
      ) : (
        <>
          <div className={styles.toolbar}>
            <div className={styles.toggle} role="tablist">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={view === t.id}
                  className={view === t.id ? styles.active : ""}
                  onClick={() => setView(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {deviceFilter && (
              <span className={styles.filterNote}>
                just {shortId(deviceFilter)}
                <button onClick={() => setDeviceFilter(null)}>clear ✕</button>
              </span>
            )}
          </div>

          {loading && <div className={styles.state}>Loading…</div>}
          {/* role=alert so a failure is announced, not just coloured */}
          {error && !loading && (
            <div className={`${styles.state} ${styles.error}`} role="alert">
              {error}
            </div>
          )}

          {!loading && !error && view === "overview" && (
            <>
              <h2 className={styles.h2}>Everything made, newest first</h2>
              {events.length === 0 ? (
                <div className={styles.state}>
                  No mixes yet — make one in the app or in Discord and
                  it&apos;ll show up here.
                </div>
              ) : (
                <div className={styles.list} data-testid="event-list">
                  {events.map((ev) => (
                    <EventRow
                      key={ev.id}
                      ev={ev}
                      expanded={expanded === ev.id}
                      playing={playing === ev.id}
                      onToggle={() =>
                        setExpanded(expanded === ev.id ? null : ev.id)
                      }
                      onPlay={() =>
                        setPlaying(playing === ev.id ? null : ev.id)
                      }
                    />
                  ))}
                </div>
              )}
              {events.length < total && (
                <button
                  className={`${styles.refresh} ${styles.more}`}
                  onClick={() => void loadMore()}
                >
                  Show more ({events.length} of {total})
                </button>
              )}
              {health && <HealthPanel health={health} />}
            </>
          )}

          {!loading && !error && view === "people" && (
            <DevicesView
              devices={devices}
              retention={retention}
              onPick={(id) => void openPerson(id)}
            />
          )}

          {!loading && !error && view === "music" && (
            <MusicPanel songs={songs} />
          )}

          {!loading &&
            !error &&
            view === "when" &&
            (time ? (
              <WhenPanel time={time} />
            ) : (
              <div className={styles.state}>
                Couldn&apos;t load the activity-over-time numbers. Refresh to
                try again.
              </div>
            ))}
        </>
      )}
    </div>
  );
}

/** How many distinct people have made anything. Prefers the by-source people counts, which
 *  include rows with no id, so this tile agrees with the retention strip below it rather than
 *  disagreeing by one (the two used different definitions before). */
function peopleCount(summary: OpsSummary | null): number | undefined {
  if (!summary) return undefined;
  const bySource = Object.values(summary.people_by_source ?? {});
  return bySource.length
    ? bySource.reduce((a, b) => a + b, 0)
    : summary.devices;
}

/** Where the work is coming from — the one number that says whether Discord is pulling its weight.
 *  'unknown' is shown honestly rather than folded into either surface: those rows were recorded
 *  before mixes were tagged, and guessing would make this split quietly wrong. */
function SourceStrip({ summary }: { summary: OpsSummary }) {
  const entries = Object.entries(summary.by_source ?? {}).sort(
    (a, b) => b[1] - a[1],
  );
  if (entries.length === 0) return null;
  const label = (k: string) =>
    k === "web" ? "web" : k === "discord" ? "Discord" : "before tagging";
  return (
    <div className={styles.retention} data-testid="source-strip">
      {entries.map(([k, n], i) => (
        <span key={k}>
          {i > 0 && <span className={styles.dotsep}>·</span>}
          <b>{n}</b> from {label(k)}
          {summary.people_by_source?.[k]
            ? ` (${summary.people_by_source[k]} ${
                summary.people_by_source[k] === 1 ? "person" : "people"
              })`
            : ""}
        </span>
      ))}
    </div>
  );
}

function Tile({
  n,
  l,
  tone,
}: {
  n?: number;
  l: string;
  tone?: "red" | "amber";
}) {
  const color =
    tone === "red"
      ? "var(--danger)"
      : tone === "amber"
        ? "var(--amber)"
        : "var(--text)";
  return (
    <div className={styles.tile}>
      <div
        style={{
          fontFamily: "var(--serif)",
          fontSize: 30,
          lineHeight: 1,
          color,
        }}
      >
        {n ?? "—"}
      </div>
      <div style={labelStyle}>{l}</div>
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 9,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--w45)",
  marginTop: 6,
};

function EventRow({
  ev,
  expanded,
  playing,
  onToggle,
  onPlay,
}: {
  ev: OpsEvent;
  expanded: boolean;
  playing: boolean;
  onToggle: () => void;
  onPlay: () => void;
}) {
  const audioUrl = ev.extra?.audio_url;
  const pair =
    ev.kind === "set"
      ? "Set of mixes"
      : `${ev.song1_name ?? "Song 1"} → ${ev.song2_name ?? "Song 2"}`;
  return (
    <>
      <div className={styles.row}>
        <button
          className={styles.rowMain}
          onClick={onToggle}
          data-testid="event-row"
        >
          <span
            className={`${styles.dot} ${styles[healthClass(ev.health)]}`}
            data-testid={`dot-${ev.health}`}
          />
          <span className={styles.songs}>
            {ev.kind === "set" ? (
              <span className={`${styles.badge} ${styles.setKind}`}>SET</span>
            ) : null}{" "}
            {pair}
          </span>
          {ev.rule_label && ev.kind !== "set" && (
            <span className={styles.badge}>{ev.rule_label}</span>
          )}
          {ev.via === "set" && <span className={styles.meta}>in set</span>}
          {ev.source === "discord" && (
            <span className={styles.badge}>Discord</span>
          )}
          <span className={styles.meta}>
            {ev.user_name ?? shortId(ev.user_id)}
          </span>
          <span className={styles.meta}>{fmtTime(ev.created_at)}</span>
        </button>
        <button
          className={styles.play}
          onClick={onPlay}
          disabled={!audioUrl}
          title={audioUrl ? "Play this mix" : "No audio (this one failed)"}
          data-testid="play"
        >
          {playing ? "❚❚" : "▶"}
        </button>
      </div>
      {expanded && (
        <div className={styles.expand}>
          {playing && audioUrl && (
            <audio
              controls
              autoPlay
              src={`${API_BASE}${audioUrl}`}
              data-testid="audio"
            />
          )}
          {ev.status === "failed" && ev.fail_reason && (
            <div className={styles.failReason}>Failed: {ev.fail_reason}</div>
          )}
          {ev.anomalies.map((a) => (
            <div className={styles.anom} key={a.code}>
              <div className={styles.code}>{a.code}</div>
              <div className={styles.txt}>{a.detail}</div>
              <div className={styles.act}>→ {a.action}</div>
            </div>
          ))}
          {ev.status === "ok" && ev.anomalies.length === 0 && (
            <div className={styles.meta}>Clean mix — no issues flagged.</div>
          )}
        </div>
      )}
      {playing && audioUrl && !expanded && (
        <div className={styles.expand}>
          <audio
            controls
            autoPlay
            src={`${API_BASE}${audioUrl}`}
            data-testid="audio"
          />
        </div>
      )}
    </>
  );
}

function DevicesView({
  devices,
  retention,
  onPick,
}: {
  devices: OpsDevice[];
  retention: OpsRetention | null;
  onPick: (id: string) => void;
}) {
  if (devices.length === 0) {
    return <div className={styles.state}>No devices yet.</div>;
  }
  return (
    <>
      {retention && (
        <div className={styles.retention} data-testid="retention-strip">
          <span>
            <b>{retention.returning_devices}</b> of {retention.total_devices}{" "}
            came back another day
          </span>
          <span className={styles.dotsep}>·</span>
          <span>
            <b>{retention.new_today}</b> new today
          </span>
          <span className={styles.dotsep}>·</span>
          <span>
            <b>{retention.returning_today}</b> returned today
          </span>
        </div>
      )}
      <div className={styles.list} data-testid="device-list">
        {devices.map((d) => (
          <button
            key={d.user_id}
            className={styles.devRow}
            onClick={() => onPick(d.user_id)}
            disabled={d.user_id === "(no id)"}
            title={
              d.user_id === "(no id)"
                ? "These mixes were made before ids were recorded, so there's no one to open."
                : "Open this person's page"
            }
          >
            {/* the recognisable name first when we have one — a bare account id tells you nothing */}
            <span className={styles.devId}>{d.user_name ?? d.user_id}</span>
            {d.source !== "unknown" && (
              <span className={styles.badge}>
                {d.source === "discord" ? "Discord" : "Web"}
              </span>
            )}
            <span className={styles.badge}>{d.total} made</span>
            {d.active_days >= 2 && (
              <span
                className={styles.badge}
                style={{ borderColor: "var(--green)", color: "var(--green)" }}
              >
                returning · {d.active_days} days
              </span>
            )}
            {d.degraded > 0 && (
              <span className={styles.meta} style={{ color: "var(--amber)" }}>
                {d.degraded} degraded
              </span>
            )}
            {d.failed > 0 && (
              <span className={styles.meta} style={{ color: "var(--danger)" }}>
                {d.failed} failed
              </span>
            )}
            <span className={styles.meta} title="first seen → last seen">
              {fmtTime(d.first_at)} → {fmtTime(d.last_at)}
            </span>
          </button>
        ))}
      </div>
      <p className={styles.retentionNote}>
        Discord rows are real accounts, so those are solid. Web rows count a
        saved browser tag, not a verified person — the same human on a phone and
        a laptop reads as two, and cleared storage reads as new. Directional
        until the web app has sign-in.
      </p>
    </>
  );
}

function TokenGate({ onSubmit }: { onSubmit: (t: string) => void }) {
  const [token, setToken] = useState("");
  return (
    <div className={styles.wrap}>
      <div className={styles.tokenBox}>
        <h1 className={styles.h1}>Dashboard locked</h1>
        <p className={styles.state}>
          This dashboard is protected. Enter the access token to continue.
        </p>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="access token"
          data-testid="token-input"
        />
        <button className={styles.refresh} onClick={() => onSubmit(token)}>
          Unlock
        </button>
      </div>
    </div>
  );
}

function healthClass(h: string): "green" | "amber" | "red" {
  return h === "red" ? "red" : h === "amber" ? "amber" : "green";
}

function shortId(id: string | null): string {
  if (!id) return "no-id";
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

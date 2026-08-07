import { useCallback, useEffect, useState } from "react";
import {
  API_BASE,
  DashboardLockedError,
  getOpsDevices,
  getOpsEvents,
  getOpsSummary,
  type OpsDevice,
  type OpsEvent,
  type OpsSummary,
} from "../../lib/api";
import styles from "./AdminScreen.module.css";

const PAGE = 50;

/** The internal developer / operations dashboard (reached at #dev). Read-only.
 *  Shows every mix/set that's been made, newest first, with failures (red) and degraded
 *  mixes (amber) called out, a play button to hear each one, and a per-device rollup.
 *  This is an ops tool, not part of the user flow — it never changes or deletes anything. */
export function AdminScreen() {
  const [view, setView] = useState<"activity" | "devices">("activity");
  const [summary, setSummary] = useState<OpsSummary | null>(null);
  const [events, setEvents] = useState<OpsEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [devices, setDevices] = useState<OpsDevice[]>([]);
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
        <Tile n={summary?.devices} l="devices" />
      </div>

      <div className={styles.toolbar}>
        <div className={styles.toggle}>
          <button
            className={view === "activity" ? styles.active : ""}
            onClick={() => setView("activity")}
          >
            Activity
          </button>
          <button
            className={view === "devices" ? styles.active : ""}
            onClick={() => setView("devices")}
          >
            By device
          </button>
        </div>
        {deviceFilter && (
          <span className={styles.filterNote}>
            device {shortId(deviceFilter)}
            <button onClick={() => setDeviceFilter(null)}>clear ✕</button>
          </span>
        )}
      </div>

      {loading && <div className={styles.state}>Loading…</div>}
      {error && !loading && (
        <div className={`${styles.state} ${styles.error}`}>{error}</div>
      )}

      {!loading && !error && view === "activity" && (
        <>
          {events.length === 0 ? (
            <div className={styles.state}>
              No mixes yet — make one in the app and it'll show up here.
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
                  onPlay={() => setPlaying(playing === ev.id ? null : ev.id)}
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
        </>
      )}

      {!loading && !error && view === "devices" && (
        <DevicesView
          devices={devices}
          onPick={(id) => {
            setDeviceFilter(id === "(no id)" ? null : id);
            setView("activity");
          }}
        />
      )}
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
          <span className={styles.meta}>{shortId(ev.user_id)}</span>
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
  onPick,
}: {
  devices: OpsDevice[];
  onPick: (id: string) => void;
}) {
  if (devices.length === 0) {
    return <div className={styles.state}>No devices yet.</div>;
  }
  return (
    <div className={styles.list} data-testid="device-list">
      {devices.map((d) => (
        <button
          key={d.user_id}
          className={styles.devRow}
          onClick={() => onPick(d.user_id)}
        >
          <span className={styles.devId}>{d.user_id}</span>
          <span className={styles.badge}>{d.total} made</span>
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
          <span className={styles.meta}>{fmtTime(d.last_at)}</span>
        </button>
      ))}
    </div>
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

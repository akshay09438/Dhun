import type {
  OpsHealthReasons,
  OpsPerson,
  OpsSong,
  OpsTime,
} from "../../lib/api";
import styles from "./AdminScreen.module.css";

/** The Music / When / Health / one-Person panels of the ops dashboard.
 *
 *  Deliberately plain: no charting library, no animation. Every "bar" is a div whose width or
 *  height is a percentage, and the exact number is ALWAYS rendered as text beside it — which is
 *  both what makes this readable at a glance and what makes it readable to a screen reader.
 *  These panels live apart from AdminScreen so the shell stays a shell; they take plain data and
 *  render it, holding no state of their own. */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// ---------------------------------------------------------------------------
// shared primitives
// ---------------------------------------------------------------------------

/** One horizontal bar: label, proportional fill, exact count. `max` scales the row against its
 *  siblings so the longest bar fills the track. */
export function BarRow({
  label,
  n,
  max,
  tone,
  title,
}: {
  label: string;
  n: number;
  max: number;
  tone?: "amber" | "red";
  title?: string;
}) {
  const pct = max > 0 ? Math.round((n / max) * 100) : 0;
  const color =
    tone === "red"
      ? "var(--danger)"
      : tone === "amber"
        ? "var(--amber)"
        : "var(--violet)";
  return (
    <div className={styles.barRow} title={title ?? `${label}: ${n}`}>
      <span className={styles.barLabel}>{label}</span>
      <span className={styles.barTrack}>
        {/* aria-hidden: the count next to it is the accessible value, so the bar is decoration */}
        <span
          className={styles.barFill}
          style={{ width: `${pct}%`, background: color }}
          aria-hidden="true"
        />
      </span>
      <span className={styles.barN}>{n}</span>
    </div>
  );
}

function EmptyPanel({ children }: { children: React.ReactNode }) {
  return <div className={styles.state}>{children}</div>;
}

/** A column-per-bucket histogram, for the two time series where the SHAPE is the point (24 hours,
 *  30 days) and one row each would be too long to scan. Every column still carries its exact count
 *  in a title and an aria-label, so no information lives only in the pixels. */
function ColumnChart({
  values,
  labelFor,
  tickEvery,
  testId,
}: {
  values: { key: string; n: number }[];
  labelFor: (key: string, n: number) => string;
  tickEvery: number;
  testId?: string;
}) {
  const max = Math.max(1, ...values.map((v) => v.n));
  return (
    <div className={styles.cols} data-testid={testId}>
      {values.map((v, i) => (
        <div className={styles.col} key={v.key}>
          <span
            className={styles.colBar}
            style={{ height: `${Math.round((v.n / max) * 100)}%` }}
            title={labelFor(v.key, v.n)}
            aria-label={labelFor(v.key, v.n)}
            role="img"
          />
          <span className={styles.colTick}>
            {i % tickEvery === 0 ? v.key : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

/** The hour-of-day and weekday pair, shared by the When tab and one person's page. */
export function TimePatterns({
  byHour,
  byWeekday,
  reportTz,
}: {
  byHour: number[];
  byWeekday: number[];
  reportTz?: string;
}) {
  const totalHours = byHour.reduce((a, b) => a + b, 0);
  const wkMax = Math.max(1, ...byWeekday);
  return (
    <>
      <h2 className={styles.h2}>By hour of day</h2>
      {totalHours === 0 ? (
        <EmptyPanel>Nothing recorded yet.</EmptyPanel>
      ) : (
        <ColumnChart
          testId="hour-chart"
          tickEvery={3}
          values={byHour.map((n, h) => ({ key: String(h), n }))}
          labelFor={(h, n) => `${h}:00 — ${n} made`}
        />
      )}
      {reportTz && (
        <p className={styles.retentionNote}>
          Hours are in <b>{reportTz}</b> — your clock, not each person&apos;s.
          Someone abroad making a mix at their 9pm still lands here at whatever
          time that was for you.
        </p>
      )}

      <h2 className={styles.h2}>By day of week</h2>
      {wkMax <= 1 && byWeekday.every((n) => n === 0) ? (
        <EmptyPanel>Nothing recorded yet.</EmptyPanel>
      ) : (
        <div className={styles.list} data-testid="weekday-chart">
          {byWeekday.map((n, i) => (
            <BarRow key={WEEKDAYS[i]} label={WEEKDAYS[i]} n={n} max={wkMax} />
          ))}
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// MUSIC — which songs people actually reach for
// ---------------------------------------------------------------------------

export function MusicPanel({ songs }: { songs: OpsSong[] }) {
  if (songs.length === 0) {
    return (
      <EmptyPanel>
        No mixes yet — once people start making them, the songs they pick show
        up here.
      </EmptyPanel>
    );
  }
  return (
    <>
      <p className={styles.retentionNote}>
        Every catalog song by how often it was picked. A song that is always
        degraded is usually the song&apos;s own analysis, not the mix engine.
      </p>
      {/* wrapped so a narrow window scrolls the table rather than the page */}
      <div className={styles.tableWrap}>
        <table className={styles.table} data-testid="song-table">
          <thead>
            <tr>
              <th>Song</th>
              <th className={styles.num}>As beat</th>
              <th className={styles.num}>As vocal</th>
              <th className={styles.num}>Degraded</th>
              <th className={styles.num}>Failed</th>
              <th>Most often with</th>
            </tr>
          </thead>
          <tbody>
            {songs.map((s) => (
              <tr key={s.song_id}>
                <td>{s.name}</td>
                <td className={styles.num}>{s.as_beat || "—"}</td>
                <td className={styles.num}>{s.as_vocal || "—"}</td>
                <td
                  className={styles.num}
                  style={s.degraded ? { color: "var(--amber)" } : undefined}
                >
                  {s.degraded || "—"}
                </td>
                <td
                  className={styles.num}
                  style={s.failed ? { color: "var(--danger)" } : undefined}
                >
                  {s.failed || "—"}
                </td>
                <td className={styles.meta}>{s.top_partner ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// WHEN — hour, weekday, and the last N days
// ---------------------------------------------------------------------------

export function WhenPanel({ time }: { time: OpsTime }) {
  const hasDays = time.by_day.length > 0;
  return (
    <>
      <h2 className={styles.h2}>Last {time.days} days</h2>
      {hasDays ? (
        <ColumnChart
          testId="day-chart"
          tickEvery={Math.max(1, Math.ceil(time.by_day.length / 8))}
          values={time.by_day.map((d) => ({ key: d.day.slice(5), n: d.n }))}
          labelFor={(day, n) => `${day} — ${n} made`}
        />
      ) : (
        <EmptyPanel>No activity recorded yet.</EmptyPanel>
      )}
      <TimePatterns
        byHour={time.by_hour}
        byWeekday={time.by_weekday}
        reportTz={time.report_tz}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// HEALTH — a ranked list of things to go and fix
// ---------------------------------------------------------------------------

export function HealthPanel({ health }: { health: OpsHealthReasons }) {
  const { failures, degradations } = health;
  if (failures.length === 0 && degradations.length === 0) {
    return <EmptyPanel>Nothing has broken or come out degraded.</EmptyPanel>;
  }
  const fMax = Math.max(1, ...failures.map((f) => f.n));
  const dMax = Math.max(1, ...degradations.map((d) => d.n));
  return (
    <>
      {failures.length > 0 && (
        <>
          <h2 className={styles.h2}>Why mixes failed</h2>
          <div className={styles.list}>
            {failures.map((f) => (
              <BarRow
                key={f.reason}
                label={f.reason}
                n={f.n}
                max={fMax}
                tone="red"
              />
            ))}
          </div>
        </>
      )}
      {degradations.length > 0 && (
        <>
          <h2 className={styles.h2}>Most common degradations</h2>
          <div className={styles.list}>
            {degradations.map((d) => (
              <BarRow
                key={d.code}
                label={d.code}
                n={d.n}
                max={dMax}
                tone="amber"
              />
            ))}
          </div>
          <p className={styles.retentionNote}>
            These played fine but something was off. They are the quality
            backlog, ranked by how often they actually happen.
          </p>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// ONE PERSON
// ---------------------------------------------------------------------------

export function PersonPanel({
  person,
  onSeeMixes,
}: {
  person: OpsPerson;
  onSeeMixes: () => void;
}) {
  if (!person.found) {
    return <EmptyPanel>This person hasn&apos;t made anything yet.</EmptyPanel>;
  }
  const beats = person.top_beats ?? [];
  const vocals = person.top_vocals ?? [];
  const bMax = Math.max(1, ...beats.map((b) => b.n));
  const vMax = Math.max(1, ...vocals.map((v) => v.n));
  return (
    <>
      <div className={styles.personHead}>
        <div>
          <p className={styles.kick}>
            {person.source === "discord"
              ? "Discord"
              : person.source === "web"
                ? "Web"
                : "Unknown source"}
          </p>
          <h2 className={styles.personName}>
            {person.user_name ?? person.user_id}
          </h2>
          <p className={styles.meta}>
            {person.first_day} → {person.last_day} · {person.active_days} active
            day
            {person.active_days === 1 ? "" : "s"} · {person.sittings} sitting
            {person.sittings === 1 ? "" : "s"}
          </p>
        </div>
        <button className={styles.refresh} onClick={onSeeMixes}>
          See their mixes
        </button>
      </div>

      <div className={styles.tiles}>
        <PersonTile n={person.total} l="made" />
        <PersonTile n={person.sets ?? 0} l="sets" />
        <PersonTile
          n={person.degraded ?? 0}
          l="degraded"
          tone={person.degraded ? "amber" : undefined}
        />
        <PersonTile
          n={person.failed ?? 0}
          l="failed"
          tone={person.failed ? "red" : undefined}
        />
        <PersonTile n={person.max_take ?? 0} l="most takes" />
      </div>

      <div className={styles.twoCol}>
        <div>
          <h2 className={styles.h2}>Their beats</h2>
          <div className={styles.list}>
            {beats.length === 0 ? (
              <EmptyPanel>None yet.</EmptyPanel>
            ) : (
              beats.map((b, i) => (
                <BarRow
                  key={`${b.name}-${i}`}
                  label={b.name ?? "—"}
                  n={b.n}
                  max={bMax}
                />
              ))
            )}
          </div>
        </div>
        <div>
          <h2 className={styles.h2}>Their vocals</h2>
          <div className={styles.list}>
            {vocals.length === 0 ? (
              <EmptyPanel>None yet.</EmptyPanel>
            ) : (
              vocals.map((v, i) => (
                <BarRow
                  key={`${v.name}-${i}`}
                  label={v.name ?? "—"}
                  n={v.n}
                  max={vMax}
                />
              ))
            )}
          </div>
        </div>
      </div>

      <TimePatterns
        byHour={person.by_hour ?? new Array(24).fill(0)}
        byWeekday={person.by_weekday ?? new Array(7).fill(0)}
        reportTz={person.report_tz}
      />

      {/* Say exactly how much this identity can be trusted — and don't claim to know when we
          don't. A pre-tagging row could be either surface, so it gets its own honest note. */}
      {person.source === "web" && (
        <p className={styles.retentionNote}>
          This is a saved browser tag, not a verified person — the same human on
          a phone and a laptop reads as two, and cleared storage reads as new.
        </p>
      )}
      {person.source !== "web" && person.source !== "discord" && (
        <p className={styles.retentionNote}>
          This activity predates source tagging, so we can&apos;t tell whether
          it came from the web app or Discord. Anything made from now on is
          tagged.
        </p>
      )}
    </>
  );
}

function PersonTile({
  n,
  l,
  tone,
}: {
  n: number;
  l: string;
  tone?: "amber" | "red";
}) {
  const color =
    tone === "red"
      ? "var(--danger)"
      : tone === "amber"
        ? "var(--amber)"
        : "var(--text)";
  return (
    <div className={styles.tile}>
      <div className={styles.n} style={{ color }}>
        {n}
      </div>
      <div className={styles.l}>{l}</div>
    </div>
  );
}

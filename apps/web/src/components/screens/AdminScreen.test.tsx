import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AdminScreen } from "./AdminScreen";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const SUMMARY = {
  total: 3,
  failed: 1,
  degraded: 1,
  devices: 2,
  today_total: 2,
  today_failed: 1,
  today_degraded: 1,
  mixes: 3,
  sets: 0,
  by_source: { web: 1, discord: 2 },
  people_by_source: { web: 1, discord: 1 },
  report_tz: "Asia/Kolkata",
};

const SONGS = [
  {
    song_id: "s1".repeat(32),
    name: "Lean On",
    as_beat: 13,
    as_vocal: 0,
    used: 13,
    failed: 0,
    degraded: 13,
    top_partner: "Khuda Jaane",
  },
  {
    song_id: "s2".repeat(32),
    name: "Khuda Jaane",
    as_beat: 0,
    as_vocal: 7,
    used: 7,
    failed: 1,
    degraded: 6,
    top_partner: "Lean On",
  },
];

const TIME = {
  by_hour: Array.from({ length: 24 }, (_, h) => (h === 19 ? 12 : 0)),
  by_weekday: [3, 9, 0, 0, 0, 0, 0],
  by_day: [
    { day: "2026-08-09", n: 4, failed: 0, degraded: 1 },
    { day: "2026-08-10", n: 8, failed: 2, degraded: 3 },
  ],
  days: 30,
  report_tz: "Asia/Kolkata",
};

const HEALTH = {
  failures: [{ reason: "No beat detected.", n: 2 }],
  degradations: [{ code: "forced_tempo", n: 5 }],
};

const PERSON = {
  user_id: "752918281408610445",
  found: true,
  total: 15,
  failed: 3,
  degraded: 8,
  sets: 2,
  first_day: "2026-08-09",
  last_day: "2026-08-10",
  active_days: 2,
  max_take: 3,
  avg_take: 1.4,
  source: "discord",
  user_name: "akshay09",
  by_hour: Array.from({ length: 24 }, (_, h) => (h === 19 ? 12 : 0)),
  by_weekday: [6, 9, 0, 0, 0, 0, 0],
  top_beats: [{ name: "Lean On", n: 3 }],
  top_vocals: [{ name: "Khuda Jaane", n: 4 }],
  sittings: 4,
  report_tz: "Asia/Kolkata",
};

const EVENTS = [
  {
    id: 3,
    created_at: "2026-08-07T12:00:00",
    kind: "mix",
    via: "single",
    ref_id: "c".repeat(64),
    user_id: "dev-2",
    song1_name: "Rapture",
    song2_name: "Uff Teri Ada",
    rule: null,
    rule_label: null,
    take: 1,
    status: "failed",
    health: "red",
    fail_reason: "The mix didn't pass the quality check.",
    anomalies: [],
    extra: {},
  },
  {
    id: 2,
    created_at: "2026-08-07T11:00:00",
    kind: "mix",
    via: "single",
    ref_id: "b".repeat(64),
    user_id: "dev-2",
    song1_name: "Innerbloom",
    song2_name: "Jugni Ji",
    rule: 4,
    rule_label: "Echo",
    take: 1,
    status: "ok",
    health: "amber",
    fail_reason: null,
    anomalies: [
      {
        code: "forced_tempo",
        detail: "Stretched ~28% onto the beat.",
        action: "Prefer a closer partner.",
        severity: "warn",
      },
    ],
    extra: { audio_url: `/mix/${"b".repeat(64)}/audio` },
  },
  {
    id: 1,
    created_at: "2026-08-07T10:00:00",
    kind: "mix",
    via: "single",
    ref_id: "a".repeat(64),
    user_id: "dev-1",
    song1_name: "Father Ocean",
    song2_name: "Der Lagi",
    rule: 1,
    rule_label: "Simple",
    take: 1,
    status: "ok",
    health: "green",
    fail_reason: null,
    anomalies: [],
    extra: { audio_url: `/mix/${"a".repeat(64)}/audio` },
  },
];

const DEVICES = [
  {
    user_id: "dev-2",
    total: 2,
    failed: 1,
    degraded: 1,
    first_at: "2026-08-05T09:00:00", // seen on an earlier day too -> returning
    last_at: "2026-08-07T12:00:00",
    first_day: "2026-08-05",
    last_day: "2026-08-07",
    active_days: 2,
    source: "discord",
    user_name: "akshay09",
  },
  {
    user_id: "dev-1",
    total: 1,
    failed: 0,
    degraded: 0,
    first_at: "2026-08-07T10:00:00",
    last_at: "2026-08-07T10:00:00",
    first_day: "2026-08-07",
    last_day: "2026-08-07",
    active_days: 1,
    source: "web",
    user_name: null,
  },
];

const RETENTION = {
  total_devices: 2,
  returning_devices: 1,
  new_today: 1,
  returning_today: 1,
};

/** Route the mocked fetch by URL. `events` may be a function of the URL (for pagination). */
function stubApi(opts?: {
  status?: number;
  events?: (url: string) => unknown;
}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (opts?.status === 401)
        return { ok: false, status: 401, json: async () => ({}) };
      const ok = (data: unknown) => ({
        ok: true,
        status: 200,
        json: async () => data,
      });
      if (url.includes("/admin/summary")) return ok(SUMMARY);
      if (url.includes("/admin/retention")) return ok(RETENTION);
      if (url.includes("/admin/devices")) return ok(DEVICES);
      if (url.includes("/admin/songs")) return ok(SONGS);
      if (url.includes("/admin/time")) return ok(TIME);
      if (url.includes("/admin/health-reasons")) return ok(HEALTH);
      if (url.includes("/admin/person/")) return ok(PERSON);
      if (url.includes("/admin/events")) {
        return ok(
          opts?.events ? opts.events(url) : { events: EVENTS, total: 3 },
        );
      }
      return { ok: false, status: 404, json: async () => ({}) };
    }),
  );
}

test("shows the health strip numbers from the summary", async () => {
  stubApi();
  render(<AdminScreen />);
  const strip = await screen.findByTestId("health-strip");
  expect(within(strip).getByText("3")).toBeTruthy(); // total (unique)
  expect(within(strip).getByText("mixes & sets")).toBeTruthy();
  expect(within(strip).getAllByText("2")).toHaveLength(2); // today total + people both = 2
  expect(within(strip).getByText("today")).toBeTruthy();
  // renamed from "devices" when the tile started counting people across web AND Discord
  expect(within(strip).getByText("people")).toBeTruthy();
});

test("lists events newest-first with the right health dots", async () => {
  stubApi();
  render(<AdminScreen />);
  const list = await screen.findByTestId("event-list");
  const rows = within(list).getAllByTestId("event-row");
  expect(rows).toHaveLength(3);
  // newest (id 3, red/failed) is first
  expect(rows[0].textContent).toContain("Rapture");
  expect(within(list).getByTestId("dot-red")).toBeTruthy();
  expect(within(list).getByTestId("dot-amber")).toBeTruthy();
  expect(within(list).getByTestId("dot-green")).toBeTruthy();
});

test("shows the auto-assigned rule label on a mix (visible to the dev, not the user)", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  expect(screen.getByText("Echo")).toBeTruthy();
  expect(screen.getByText("Simple")).toBeTruthy();
});

test("a failed mix has no playable audio; a good one does", async () => {
  stubApi();
  render(<AdminScreen />);
  const list = await screen.findByTestId("event-list");
  const plays = within(list).getAllByTestId("play");
  expect((plays[0] as HTMLButtonElement).disabled).toBe(true); // failed row -> no audio
  expect((plays[1] as HTMLButtonElement).disabled).toBe(false); // amber ok row -> playable
});

test("clicking play reveals an audio element for that mix", async () => {
  stubApi();
  render(<AdminScreen />);
  const list = await screen.findByTestId("event-list");
  const plays = within(list).getAllByTestId("play");
  fireEvent.click(plays[1]); // the amber, playable mix
  const audio = await screen.findByTestId("audio");
  expect((audio as HTMLAudioElement).getAttribute("src")).toContain(
    `/mix/${"b".repeat(64)}/audio`,
  );
});

test("expanding a degraded row shows the anomaly detail and suggested action", async () => {
  stubApi();
  render(<AdminScreen />);
  const list = await screen.findByTestId("event-list");
  const rows = within(list).getAllByTestId("event-row");
  fireEvent.click(rows[1]); // the amber, forced-tempo mix
  expect(await screen.findByText(/Stretched ~28% onto the beat/)).toBeTruthy();
  expect(screen.getByText(/Prefer a closer partner/)).toBeTruthy();
});

test("expanding a failed row shows the plain-language failure reason", async () => {
  stubApi();
  render(<AdminScreen />);
  const list = await screen.findByTestId("event-list");
  const rows = within(list).getAllByTestId("event-row");
  fireEvent.click(rows[0]); // the red, failed mix
  expect(await screen.findByText(/didn't pass the quality check/)).toBeTruthy();
});

test("the 'people' view lists people busiest-first", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByText("People"));
  const devList = await screen.findByTestId("device-list");
  // dev-2 now renders by DISPLAY NAME where we have one — a bare account id tells the
  // operator nothing. Its raw id is still the key; only the label changed.
  expect(within(devList).getByText("akshay09")).toBeTruthy();
  expect(within(devList).getByText("2 made")).toBeTruthy();
  // ordering is still the point of this test: busiest (2 made) before quieter (1 made)
  const rows = within(devList).getAllByRole("button");
  expect(rows[0].textContent).toContain("2 made");
  expect(rows[1].textContent).toContain("1 made");
});

test("the 'by device' view shows the retention strip and a returning badge", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByText("People"));
  const strip = await screen.findByTestId("retention-strip");
  expect(strip.textContent).toContain("came back another day");
  expect(strip.textContent).toContain("new today");
  // dev-2 was active on 2 days -> a "returning · N days" badge; dev-1 (1 day) gets none
  expect(screen.getByText(/returning · 2 days/)).toBeTruthy();
});

test("retention failing does not break the core dashboard (loads independently)", async () => {
  // retention 404s; everything else is fine -> the activity feed still renders, no error state.
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const ok = (data: unknown) => ({
        ok: true,
        status: 200,
        json: async () => data,
      });
      if (url.includes("/admin/retention"))
        return { ok: false, status: 404, json: async () => ({}) };
      if (url.includes("/admin/summary")) return ok(SUMMARY);
      if (url.includes("/admin/devices")) return ok(DEVICES);
      if (url.includes("/admin/events"))
        return ok({ events: EVENTS, total: 3 });
      return { ok: false, status: 404, json: async () => ({}) };
    }),
  );
  render(<AdminScreen />);
  const list = await screen.findByTestId("event-list");
  expect(within(list).getAllByTestId("event-row")).toHaveLength(3);
  // devices view still works; it just shows no retention strip
  fireEvent.click(screen.getByText("People"));
  await screen.findByTestId("device-list");
  expect(screen.queryByTestId("retention-strip")).toBeNull();
});

test("empty state when nothing has been made yet", async () => {
  stubApi({ events: () => ({ events: [], total: 0 }) });
  render(<AdminScreen />);
  expect(await screen.findByText(/No mixes yet/)).toBeTruthy();
});

test("a locked dashboard (401) shows the token gate", async () => {
  stubApi({ status: 401 });
  render(<AdminScreen />);
  expect(await screen.findByTestId("token-input")).toBeTruthy();
  expect(screen.getByText(/Dashboard locked/)).toBeTruthy();
});

test("'show more' pages through and appends the next batch", async () => {
  const first = EVENTS.slice(0, 2);
  stubApi({
    events: (url) =>
      url.includes("offset=2")
        ? { events: [EVENTS[2]], total: 3 }
        : { events: first, total: 3 },
  });
  render(<AdminScreen />);
  const list = await screen.findByTestId("event-list");
  expect(within(list).getAllByTestId("event-row")).toHaveLength(2);
  fireEvent.click(screen.getByText(/Show more/));
  await waitFor(() =>
    expect(
      within(screen.getByTestId("event-list")).getAllByTestId("event-row"),
    ).toHaveLength(3),
  );
});

// --- the four tabs, the source split, and the per-person page (2026-08-10) ------------------

test("the four tabs are present and Overview is the landing view", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
  expect(tabs).toEqual(["Overview", "People", "Music", "When"]);
  expect(
    screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected"),
  ).toBe("true");
});

test("the source strip separates web from Discord, and says which is which", async () => {
  stubApi();
  render(<AdminScreen />);
  const strip = await screen.findByTestId("source-strip");
  expect(strip.textContent).toContain("Discord");
  expect(strip.textContent).toContain("web");
});

test("a row made in Discord is badged, and shows the person's name not their raw id", async () => {
  stubApi({
    events: () => ({
      events: [{ ...EVENTS[2], source: "discord", user_name: "akshay09" }],
      total: 1,
    }),
  });
  render(<AdminScreen />);
  const list = await screen.findByTestId("event-list");
  expect(within(list).getByText("Discord")).toBeTruthy();
  expect(within(list).getByText("akshay09")).toBeTruthy();
});

test("the Music tab shows per-song beat/vocal usage and the top partner", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByRole("tab", { name: "Music" }));
  const table = await screen.findByTestId("song-table");
  // "Lean On" appears twice on purpose — as its own row, and as Khuda Jaane's top partner
  expect(within(table).getAllByText("Lean On")).toHaveLength(2);
  const leanOnRow = within(table).getAllByRole("row")[1];
  expect(leanOnRow.textContent).toContain("13"); // used as a beat 13 times
  expect(leanOnRow.textContent).toContain("Khuda Jaane"); // its most frequent partner
});

test("the When tab renders an hour, weekday and day view, and names the timezone", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByRole("tab", { name: "When" }));
  expect(await screen.findByTestId("hour-chart")).toBeTruthy();
  expect(screen.getByTestId("weekday-chart")).toBeTruthy();
  expect(screen.getByTestId("day-chart")).toBeTruthy();
  // the honest caveat: these are the operator's hours, not each person's
  expect(screen.getByText(/Asia\/Kolkata/)).toBeTruthy();
});

test("every bar carries its exact count as an accessible label, not just a height", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByRole("tab", { name: "When" }));
  const hours = await screen.findByTestId("hour-chart");
  // 19:00 has 12 in the fixture — the value must be readable without seeing the pixels
  expect(within(hours).getByLabelText("19:00 — 12 made")).toBeTruthy();
});

test("clicking a person opens their page with their songs, sittings and hours", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByRole("tab", { name: "People" }));
  const list = await screen.findByTestId("device-list");
  fireEvent.click(within(list).getAllByRole("button")[0]);

  expect(await screen.findByText("akshay09")).toBeTruthy();
  expect(screen.getByText(/4 sittings/)).toBeTruthy();
  expect(screen.getByText("Lean On")).toBeTruthy(); // their top beat
  expect(screen.getByText("Khuda Jaane")).toBeTruthy(); // their top vocal
  expect(screen.getByTestId("hour-chart")).toBeTruthy(); // their own hour pattern
});

test("the person page can be backed out of, returning to the people list", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByRole("tab", { name: "People" }));
  const list = await screen.findByTestId("device-list");
  fireEvent.click(within(list).getAllByRole("button")[0]);
  fireEvent.click(await screen.findByTestId("person-back"));
  expect(await screen.findByTestId("device-list")).toBeTruthy();
});

test("a device with no id cannot be opened (there is no one to show)", async () => {
  // Rows recorded before ids existed group under "(no id)" — that is several people pooled, so
  // opening it would show a meaningless merged page. It must be inert rather than misleading.
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const ok = (data: unknown) => ({
        ok: true,
        status: 200,
        json: async () => data,
      });
      if (url.includes("/admin/summary")) return ok(SUMMARY);
      if (url.includes("/admin/devices"))
        return ok([
          {
            ...DEVICES[0],
            user_id: "(no id)",
            user_name: null,
            source: "unknown",
          },
        ]);
      if (url.includes("/admin/events"))
        return ok({ events: EVENTS, total: 3 });
      return { ok: false, status: 404, json: async () => ({}) };
    }),
  );
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByRole("tab", { name: "People" }));
  const rows = within(await screen.findByTestId("device-list")).getAllByRole(
    "button",
  );
  expect((rows[0] as HTMLButtonElement).disabled).toBe(true);
});

test("the ranked 'what is breaking' panel appears on Overview", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  expect(screen.getByText("No beat detected.")).toBeTruthy();
  expect(screen.getByText("forced_tempo")).toBeTruthy();
});

test("a rollup that fails to load never breaks the core feed", async () => {
  // songs/time/health all 404 — the failure-visibility feed must still render.
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const ok = (data: unknown) => ({
        ok: true,
        status: 200,
        json: async () => data,
      });
      if (url.includes("/admin/summary")) return ok(SUMMARY);
      if (url.includes("/admin/devices")) return ok(DEVICES);
      if (url.includes("/admin/events"))
        return ok({ events: EVENTS, total: 3 });
      return { ok: false, status: 500, json: async () => ({}) };
    }),
  );
  render(<AdminScreen />);
  expect(await screen.findByTestId("event-list")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "Music" }));
  expect(await screen.findByText(/No mixes yet/)).toBeTruthy(); // empty, not crashed
});

test("a dashboard-level error is announced, not just coloured", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })),
  );
  render(<AdminScreen />);
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBeTruthy();
});

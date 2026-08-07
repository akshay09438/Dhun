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
    active_days: 2,
  },
  {
    user_id: "dev-1",
    total: 1,
    failed: 0,
    degraded: 0,
    first_at: "2026-08-07T10:00:00",
    last_at: "2026-08-07T10:00:00",
    active_days: 1,
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
  expect(within(strip).getAllByText("2")).toHaveLength(2); // today total + devices both = 2
  expect(within(strip).getByText("today")).toBeTruthy();
  expect(within(strip).getByText("devices")).toBeTruthy();
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

test("the 'by device' view lists devices busiest-first", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByText("By device"));
  const devList = await screen.findByTestId("device-list");
  expect(within(devList).getByText("dev-2")).toBeTruthy();
  expect(within(devList).getByText("2 made")).toBeTruthy();
});

test("the 'by device' view shows the retention strip and a returning badge", async () => {
  stubApi();
  render(<AdminScreen />);
  await screen.findByTestId("event-list");
  fireEvent.click(screen.getByText("By device"));
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
  fireEvent.click(screen.getByText("By device"));
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

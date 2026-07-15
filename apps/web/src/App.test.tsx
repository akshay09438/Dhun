import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ID1 = "a".repeat(64);
const ID2 = "c".repeat(64);

const LIBRARY = {
  songs: [
    {
      id: ID1,
      original_name: "Father Ocean",
      url: `/songs/${ID1}/audio`,
      status: "ready",
      role_hint: "beat",
    },
    {
      id: ID2,
      original_name: "Tere Bina",
      url: `/songs/${ID2}/audio`,
      status: "ready",
      role_hint: "vocals",
    },
  ],
};

const READY_MIX = {
  mix_id: "m",
  status: "ready",
  url: "/mix/m/audio",
  plan: {
    master_bpm: 122,
    vocal_stretch: 0.976,
    anchor: 16,
    beat_breath: false,
    take: 1,
    placements: [
      { anchor: 16, vocal_src: [0, 12], beat_breath: false, fx: null },
    ],
    s1_vocal_regions: [],
    notes: "Vocal weaves in at 0:16.",
    source: "rules",
  },
  message: null,
};

const READY_SET = {
  set_id: "s",
  status: "ready",
  url: "/set/s/audio",
  members: [
    {
      index: 1,
      song1_id: ID1,
      song2_id: ID2,
      kept: true,
      seam_at: null,
      reason: null,
    },
    {
      index: 2,
      song1_id: ID1,
      song2_id: ID2,
      kept: true,
      seam_at: 30,
      reason: null,
    },
  ],
  duration: 120,
  message: null,
};

/** A backend where the catalog is loaded and every study/build step is instantly ready. */
function mockBackend() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, opts?: { method?: string }) => {
      const u = String(url);
      const method = opts?.method ?? "GET";
      if (u.endsWith("/library"))
        return Promise.resolve({ ok: true, json: async () => LIBRARY });
      if (u.includes("/stems"))
        return Promise.resolve({
          ok: true,
          json: async () => ({
            song_id: "x",
            status: "ready",
            stems: { vocals: "/v" },
          }),
        });
      if (u.includes("/analysis"))
        return Promise.resolve({
          ok: true,
          json: async () => ({
            song_id: "x",
            status: "ready",
            bpm: 122,
            key: null,
            sections: [],
          }),
        });
      if (u.endsWith("/mix/name") && method === "POST")
        return Promise.resolve({
          ok: true,
          json: async () => ({ name: "Ocean Bina" }),
        });
      if (u.endsWith("/mix") && method === "POST")
        return Promise.resolve({ ok: true, json: async () => READY_MIX });
      if (u.endsWith("/set") && method === "POST")
        return Promise.resolve({ ok: true, json: async () => READY_SET });
      if (u.includes("/live/suggestions"))
        return Promise.resolve({
          ok: true,
          json: async () => ({ sections: [] }),
        });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }),
  );
}

async function pickBothSongs() {
  fireEvent.click(screen.getByTestId("song-slot-1"));
  fireEvent.click(await screen.findByRole("option", { name: /father ocean/i }));
  fireEvent.click(screen.getByTestId("song-slot-2"));
  fireEvent.click(await screen.findByRole("option", { name: /tere bina/i }));
}

describe("App — the catalog flow", () => {
  it("opens on Setup with 'Mix it' disabled until both songs are picked", () => {
    mockBackend();
    render(<App />);
    const btn = screen.getByRole("button", {
      name: /mix it/i,
    }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("has no file inputs anywhere — songs come from the catalog only", () => {
    mockBackend();
    const { container } = render(<App />);
    expect(container.querySelector('input[type="file"]')).toBeNull();
  });

  it("picks two catalog songs → generating → lands on the stripped Play screen (no steering)", async () => {
    mockBackend();
    render(<App />);
    await pickBothSongs();

    const btn = screen.getByRole("button", {
      name: /mix it/i,
    }) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);

    // Lands on Play, named, with a one-set line-up and NO live-steering controls.
    await waitFor(() =>
      expect(screen.getAllByText(/ocean bina/i).length).toBeGreaterThan(0),
    );
    expect(screen.getByTestId("set-lineup")).toBeTruthy();
    expect(screen.getByTestId("lineup-1")).toBeTruthy();
    expect(screen.queryByTestId("beat-up")).toBeNull();
    expect(screen.queryByTestId("bus-vocals")).toBeNull();
  });

  it("stacks two sets → builds a continuous set → Play shows both back-to-back", async () => {
    mockBackend();
    render(<App />);

    // Set 1
    await pickBothSongs();
    fireEvent.click(screen.getByTestId("add-set"));
    // Set 2 (reuse the same catalog songs — the flow, not the pairing, is under test)
    await pickBothSongs();

    fireEvent.click(screen.getByRole("button", { name: /build the set/i }));

    await waitFor(() => expect(screen.getByTestId("lineup-1")).toBeTruthy());
    expect(screen.getByTestId("lineup-2")).toBeTruthy();
    expect(screen.getByText(/back-to-back/i)).toBeTruthy();
  });

  it("shows only beats in Song 1 and only vocals in Song 2", async () => {
    mockBackend();
    render(<App />);

    fireEvent.click(screen.getByTestId("song-slot-1"));
    expect(
      await screen.findByRole("option", { name: /father ocean/i }),
    ).toBeTruthy();
    expect(screen.queryByRole("option", { name: /tere bina/i })).toBeNull();

    fireEvent.click(screen.getByTestId("song-slot-2"));
    expect(
      await screen.findByRole("option", { name: /tere bina/i }),
    ).toBeTruthy();
    expect(screen.queryByRole("option", { name: /father ocean/i })).toBeNull();
  });
});

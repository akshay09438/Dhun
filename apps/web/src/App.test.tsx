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

const READY_MIX = {
  mix_id: "m",
  status: "ready",
  url: "/mix/m/audio",
  plan: {
    master_bpm: 120,
    vocal_stretch: 1.0,
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

/** A backend where every step is instantly ready (the cached-demo-pair case). */
function mockBackend() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, opts?: { method?: string }) => {
      const u = String(url);
      const method = opts?.method ?? "GET";
      if (u.endsWith("/songs") && method === "POST")
        return Promise.resolve({
          ok: true,
          json: async () => ({
            songs: [
              {
                id: "a",
                original_name: "father ocean.mp3",
                url: "/songs/a/audio",
                status: "ready",
              },
              {
                id: "b",
                original_name: "tere bina.wav",
                url: "/songs/b/audio",
                status: "ready",
              },
            ],
          }),
        });
      if (u.includes("/stems"))
        return Promise.resolve({
          ok: true,
          json: async () => ({
            song_id: "a",
            status: "ready",
            stems: { vocals: "/v" },
          }),
        });
      if (u.includes("/analysis"))
        return Promise.resolve({
          ok: true,
          json: async () => ({
            song_id: "a",
            status: "ready",
            bpm: 120,
            key: null,
            sections: [],
          }),
        });
      if (u.endsWith("/mix/name") && method === "POST")
        return Promise.resolve({
          ok: true,
          json: async () => ({ name: "Tere Ocean" }),
        });
      if (u.endsWith("/mix") && method === "POST")
        return Promise.resolve({ ok: true, json: async () => READY_MIX });
      if (u.includes("/live/suggestions"))
        return Promise.resolve({
          ok: true,
          json: async () => ({ sections: [] }),
        });
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }),
  );
}

function pickBothSongs() {
  const in1 = screen.getByLabelText(/choose song one/i);
  const in2 = screen.getByLabelText(/choose song two/i);
  fireEvent.change(in1, { target: { files: [new File([""], "beat.wav")] } });
  fireEvent.change(in2, { target: { files: [new File([""], "voc.wav")] } });
}

describe("App — the four-screen flow", () => {
  it("opens on Setup with 'Mix it' disabled until both songs are chosen", () => {
    render(<App />);
    const btn = screen.getByRole("button", {
      name: /mix it/i,
    }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("runs upload → generating → play and lands on the mix with its AI name and controls", async () => {
    mockBackend();
    render(<App />);
    pickBothSongs();
    fireEvent.click(screen.getByRole("button", { name: /mix it/i }));

    // Lands on the Play screen with the AI-generated name and the live controls.
    await waitFor(() =>
      expect(screen.getAllByText(/tere ocean/i).length).toBeGreaterThan(0),
    );
    expect(screen.getByTestId("beat-up")).toBeTruthy();
    expect(screen.getByTestId("bus-drums")).toBeTruthy();
    expect(screen.getByTestId("bus-vocals")).toBeTruthy();
  });
});

import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { Uploader } from "./Uploader";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function pickBothSongs() {
  const inputs = screen.getAllByLabelText(/choose/i);
  fireEvent.change(inputs[0], {
    target: { files: [new File([""], "beat.wav")] },
  });
  fireEvent.change(inputs[1], {
    target: { files: [new File([""], "voc.wav")] },
  });
}

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

/** A backend where everything is instantly ready — the cached-demo-pair case. */
function mockAllReady() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, opts?: { method?: string }) => {
      const u = String(url);
      const method = opts?.method ?? "GET";
      if (u.endsWith("/songs") && method === "POST") {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            songs: [
              {
                id: "a",
                original_name: "beat.wav",
                url: "/songs/a/audio",
                status: "ready",
              },
              {
                id: "b",
                original_name: "voc.wav",
                url: "/songs/b/audio",
                status: "ready",
              },
            ],
          }),
        });
      }
      if (u.includes("/stems")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            song_id: "a",
            status: "ready",
            stems: { vocals: "/v" },
          }),
        });
      }
      if (u.includes("/analysis")) {
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
      }
      if (u.endsWith("/mix") && method === "POST") {
        return Promise.resolve({ ok: true, json: async () => READY_MIX });
      }
      // /live/* and anything else — benign so LiveMix mounts without throwing.
      if (u.includes("/live/context")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ bpm: 120, downbeats: [0, 2, 4] }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ sections: [] }),
      });
    }),
  );
}

describe("Uploader — one-click studying flow", () => {
  it("disables 'Make my mix' until both songs are chosen", () => {
    render(<Uploader />);
    const btn = screen.getByRole("button", {
      name: /make my mix/i,
    }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("runs upload → split → analyze → plan hands-free and lands on the mix", async () => {
    mockAllReady();
    render(<Uploader />);
    pickBothSongs();
    fireEvent.click(screen.getByRole("button", { name: /make my mix/i }));

    // The studying screen appears (no manual Split/Analyze buttons anywhere).
    expect(
      screen.queryByRole("button", { name: /split into parts/i }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: /analyze track/i })).toBeNull();

    // …then it lands on the finished mix without another click.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /give me another take/i }),
      ).toBeTruthy(),
    );
    expect(screen.getByTestId("mix-player")).toBeTruthy();
  });

  it("shows a plain-language error and a Start over button if a step fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, opts?: { method?: string }) => {
        const u = String(url);
        const method = opts?.method ?? "GET";
        if (u.endsWith("/songs") && method === "POST") {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              songs: [
                {
                  id: "a",
                  original_name: "beat.wav",
                  url: "/songs/a/audio",
                  status: "ready",
                },
                {
                  id: "b",
                  original_name: "voc.wav",
                  url: "/songs/b/audio",
                  status: "ready",
                },
              ],
            }),
          });
        }
        if (u.includes("/stems")) {
          // Split fails → the studying screen should surface it.
          return Promise.resolve({
            ok: true,
            json: async () => ({ song_id: "a", status: "error", stems: {} }),
          });
        }
        return Promise.resolve({ ok: true, json: async () => ({}) });
      }),
    );

    render(<Uploader />);
    pickBothSongs();
    fireEvent.click(screen.getByRole("button", { name: /make my mix/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/split failed/i),
    );
    expect(screen.getByRole("button", { name: /start over/i })).toBeTruthy();
  });

  it("shows the server's message when the upload itself fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ detail: "not audio" }),
      }),
    );
    render(<Uploader />);
    pickBothSongs();
    fireEvent.click(screen.getByRole("button", { name: /make my mix/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/not audio/i),
    );
  });
});

import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { MixMaker } from "./Mix";
import type { SongDTO } from "../../lib/api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const song1: SongDTO = {
  id: "a",
  original_name: "beat.wav",
  url: "/songs/a/audio",
  status: "ready",
};
const song2: SongDTO = {
  id: "b",
  original_name: "voc.wav",
  url: "/songs/b/audio",
  status: "ready",
};

function readyPlan(take = 1) {
  return {
    mix_id: "m",
    status: "ready",
    url: "/mix/m/audio",
    plan: {
      master_bpm: 120,
      vocal_stretch: 1.0,
      anchor: 16,
      beat_breath: false,
      take,
      placements: [
        { anchor: 16, vocal_src: [0, 12], beat_breath: false, fx: null },
        { anchor: 64, vocal_src: [0, 12], beat_breath: true, fx: "sweep_in" },
      ],
      s1_vocal_regions: [[30, 42]], // Song 1's own vocal answers in the gap
      notes:
        "Vocal weaves in at 0:16, 1:04. Song 1's own vocal answers in a gap.",
      source: "rules",
    },
    message: null,
  };
}

describe("MixMaker", () => {
  it("arranges the mix and shows the timeline, the take, and Regenerate", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, opts?: { method?: string }) => {
        if (String(url).endsWith("/mix") && opts?.method === "POST") {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              mix_id: "m",
              status: "processing",
              url: null,
              plan: null,
              message: null,
            }),
          });
        }
        return Promise.resolve({ ok: true, json: async () => readyPlan(1) });
      }),
    );

    render(<MixMaker song1={song1} song2={song2} />);
    fireEvent.click(screen.getByRole("button", { name: /make my mix/i }));

    await waitFor(() => {
      expect(screen.getAllByTestId("vocal-block")).toHaveLength(2); // the weave is shown
      expect(screen.getByTestId("s1-vocal-block")).toBeTruthy(); // Song 1's vocal answers
      expect(screen.getByText(/take 1/i)).toBeTruthy();
      expect(
        screen.getByRole("button", { name: /give me another take/i }),
      ).toBeTruthy();
      expect(
        screen.getByRole("button", { name: /download the mix/i }),
      ).toBeTruthy();
    });
  });

  it("regenerate asks the backend for the next take", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string, opts?: { method?: string }) => {
        if (String(url).endsWith("/mix") && opts?.method === "POST") {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              mix_id: "m",
              status: "processing",
              url: null,
              plan: null,
              message: null,
            }),
          });
        }
        return Promise.resolve({ ok: true, json: async () => readyPlan(1) });
      });
    vi.stubGlobal("fetch", fetchMock);

    render(<MixMaker song1={song1} song2={song2} />);
    fireEvent.click(screen.getByRole("button", { name: /make my mix/i }));
    await screen.findByRole("button", { name: /give me another take/i });

    fireEvent.click(
      screen.getByRole("button", { name: /give me another take/i }),
    );

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(
        ([, o]) => o?.method === "POST",
      );
      const tookSecond = posts.some(([, o]) => JSON.parse(o.body).take === 2);
      expect(tookSecond).toBe(true);
    });
  });

  it("surfaces a plain-language reason when the pair can't be mixed yet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ detail: "Song 1 hasn't been analyzed yet." }),
      }),
    );

    render(<MixMaker song1={song1} song2={song2} />);
    fireEvent.click(screen.getByRole("button", { name: /make my mix/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(
        /hasn't been analyzed/i,
      ),
    );
  });
});

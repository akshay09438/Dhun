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

describe("MixMaker", () => {
  it("makes a mix and shows the player, the DJ note, and a download", async () => {
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
        // GET /mix/m — ready
        return Promise.resolve({
          ok: true,
          json: async () => ({
            mix_id: "m",
            status: "ready",
            url: "/mix/m/audio",
            plan: {
              master_bpm: 120,
              vocal_stretch: 1.0,
              anchor: 64,
              beat_breath: false,
              notes:
                "Song 2's vocal enters on the drop at 1:04, tempo-locked to Song 1.",
              source: "rules",
            },
            message: null,
          }),
        });
      }),
    );

    render(<MixMaker song1={song1} song2={song2} />);
    fireEvent.click(screen.getByRole("button", { name: /make my mix/i }));

    await waitFor(() => {
      expect(screen.getByTestId("mix-player")).toBeTruthy();
      expect(screen.getByText(/enters on the drop at 1:04/i)).toBeTruthy();
      expect(
        screen.getByRole("button", { name: /download the mix/i }),
      ).toBeTruthy();
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

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

describe("Uploader", () => {
  it("disables Process until both songs are chosen", () => {
    render(<Uploader />);
    const btn = screen.getByRole("button", {
      name: /process/i,
    }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("shows two players after a successful upload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
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
      }),
    );

    render(<Uploader />);
    pickBothSongs();
    fireEvent.click(screen.getByRole("button", { name: /process/i }));

    await waitFor(() =>
      expect(screen.getAllByTestId("player")).toHaveLength(2),
    );
  });

  it("shows an error message when the upload fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ detail: "not audio" }),
      }),
    );

    render(<Uploader />);
    pickBothSongs();
    fireEvent.click(screen.getByRole("button", { name: /process/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/not audio/i),
    );
  });

  it("splits a song into its parts on demand", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, opts?: { method?: string }) => {
        if (String(url).endsWith("/songs")) {
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
        if (
          String(url).includes("/stems") &&
          (opts?.method ?? "GET") === "POST"
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              song_id: "a",
              status: "processing",
              stems: {},
            }),
          });
        }
        if (String(url).includes("/stems")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              song_id: "a",
              status: "ready",
              stems: {
                vocals: "/songs/a/stems/vocals",
                drums: "/songs/a/stems/drums",
                bass: "/songs/a/stems/bass",
                other: "/songs/a/stems/other",
              },
            }),
          });
        }
        return Promise.resolve({
          ok: false,
          json: async () => ({ detail: "?" }),
        });
      }),
    );

    render(<Uploader />);
    pickBothSongs();
    fireEvent.click(screen.getByRole("button", { name: /process/i }));

    const splitButtons = await screen.findAllByRole("button", {
      name: /split into parts/i,
    });
    fireEvent.click(splitButtons[0]);

    await waitFor(() =>
      expect(screen.getAllByTestId("stem-player")).toHaveLength(4),
    );
  });
});

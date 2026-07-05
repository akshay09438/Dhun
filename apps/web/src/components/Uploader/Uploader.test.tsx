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
});

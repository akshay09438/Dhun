import { describe, it, expect, vi, afterEach } from "vitest";
import { uploadSongs } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("uploadSongs", () => {
  it("returns songs on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          songs: [
            {
              id: "a",
              original_name: "x",
              url: "/songs/a/audio",
              status: "ready",
            },
          ],
        }),
      }),
    );

    const out = await uploadSongs(
      new File([""], "x.wav"),
      new File([""], "y.wav"),
    );
    expect(out.songs).toHaveLength(1);
  });

  it("throws the server's message on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ detail: "nope" }),
      }),
    );

    await expect(
      uploadSongs(new File([""], "x"), new File([""], "y")),
    ).rejects.toThrow("nope");
  });
});

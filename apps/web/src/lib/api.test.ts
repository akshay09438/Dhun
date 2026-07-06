import { describe, it, expect, vi, afterEach } from "vitest";
import { uploadSongs, postLiveCommand, getLiveContext } from "./api";

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

describe("postLiveCommand", () => {
  it("returns the parsed op", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          op: "mute",
          target: "bass",
          when: "next_bar",
          say: "dropping the bass",
          reason: null,
        }),
      }),
    );
    const op = await postLiveCommand(
      "a".repeat(64),
      "b".repeat(64),
      "take the bass out",
    );
    expect(op.op).toBe("mute");
    expect(op.target).toBe("bass");
  });
});

describe("getLiveContext", () => {
  it("returns bpm and downbeats", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ bpm: 122, downbeats: [0, 2, 4] }),
      }),
    );
    const ctx = await getLiveContext("a".repeat(64));
    expect(ctx.bpm).toBe(122);
    expect(ctx.downbeats).toEqual([0, 2, 4]);
  });
});

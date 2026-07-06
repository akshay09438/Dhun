import { describe, it, expect, vi, afterEach, test } from "vitest";
import { uploadSongs, postLiveCommand, getLiveContext } from "./api";
import { fetchVocalBus } from "./api";

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

test("fetchVocalBus polls past 202 and returns the audio bytes", async () => {
  const calls: number[] = [];
  const g = globalThis as unknown as { fetch: typeof fetch };
  const real = g.fetch;
  g.fetch = (async () => {
    calls.push(1);
    if (calls.length < 2) return new Response(null, { status: 202 });
    return new Response(new Uint8Array([1, 2, 3]), { status: 200 });
  }) as typeof fetch;
  try {
    const buf = await fetchVocalBus("a".repeat(64));
    expect(new Uint8Array(buf)).toEqual(new Uint8Array([1, 2, 3]));
    expect(calls.length).toBe(2);
  } finally {
    g.fetch = real;
  }
}, 10000);

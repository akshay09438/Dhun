import { describe, it, expect, vi, afterEach, test } from "vitest";
import { uploadSongs, postLiveCommand, getLiveContext } from "./api";
import { fetchVocalBus, getSuggestions } from "./api";
import { splitSong, analyzeSong, makeMix, getMixName, getLibrary } from "./api";

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

test("splitSong polls past 'processing' until the parts are ready", async () => {
  let gets = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((_url: string, opts?: { method?: string }) => {
      if ((opts?.method ?? "GET") === "POST")
        return Promise.resolve({
          ok: true,
          json: async () => ({ song_id: "a", status: "processing", stems: {} }),
        });
      gets++;
      return Promise.resolve({
        ok: true,
        json: async () => ({
          song_id: "a",
          status: gets >= 2 ? "ready" : "processing",
          stems: gets >= 2 ? { vocals: "/v" } : {},
        }),
      });
    }),
  );
  const out = await splitSong("a".repeat(64), { pollMs: 0, maxTries: 5 });
  expect(out.status).toBe("ready");
});

test("analyzeSong returns immediately when the POST is already ready", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        song_id: "a",
        status: "ready",
        bpm: 120,
        key: null,
        sections: [],
      }),
    }),
  );
  const out = await analyzeSong("a".repeat(64), { pollMs: 0, maxTries: 5 });
  expect(out.status).toBe("ready");
});

test("makeMix polls past 'processing' and returns the ready mix", async () => {
  let gets = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, opts?: { method?: string }) => {
      if (String(url).endsWith("/mix") && opts?.method === "POST")
        return Promise.resolve({
          ok: true,
          json: async () => ({ mix_id: "m", status: "processing", url: null }),
        });
      gets++;
      return Promise.resolve({
        ok: true,
        json: async () => ({
          mix_id: "m",
          status: gets >= 2 ? "ready" : "processing",
          url: gets >= 2 ? "/mix/m/audio" : null,
          plan: null,
          message: null,
        }),
      });
    }),
  );
  const out = await makeMix("a".repeat(64), "b".repeat(64), "", 1, {
    pollMs: 0,
    maxTries: 5,
  });
  expect(out.status).toBe("ready");
  expect(out.url).toBe("/mix/m/audio");
});

test("makeMix surfaces the backend's plain-language error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, opts?: { method?: string }) => {
      if (String(url).endsWith("/mix") && opts?.method === "POST")
        return Promise.resolve({
          ok: true,
          json: async () => ({ mix_id: "m", status: "processing" }),
        });
      return Promise.resolve({
        ok: true,
        json: async () => ({
          mix_id: "m",
          status: "error",
          message: "This pair couldn't be mixed. Try another.",
        }),
      });
    }),
  );
  await expect(
    makeMix("a".repeat(64), "b".repeat(64), "", 1, { pollMs: 0, maxTries: 5 }),
  ).rejects.toThrow(/couldn't be mixed/i);
});

test("getLibrary returns the curated catalog", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        songs: [
          {
            id: "a".repeat(64),
            original_name: "Father Ocean",
            url: "/songs/a/audio",
            status: "ready",
            role_hint: "beat",
          },
        ],
      }),
    }),
  );
  const songs = await getLibrary();
  expect(songs).toHaveLength(1);
  expect(songs[0].original_name).toBe("Father Ocean");
});

test("getMixName returns the AI-coined name", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ name: "Tere Ocean" }),
    }),
  );
  const name = await getMixName("father ocean.mp3", "tere bina.wav", "");
  expect(name).toBe("Tere Ocean");
});

test("getSuggestions returns the sections array", async () => {
  const g = globalThis as unknown as { fetch: typeof fetch };
  const real = g.fetch;
  g.fetch = (async () =>
    new Response(
      JSON.stringify({
        sections: [
          {
            start: 0,
            end: 30,
            label: "intro",
            chips: [{ text: "A", op: "mute", targets: ["bass"] }],
          },
        ],
      }),
      { status: 200 },
    )) as typeof fetch;
  try {
    const secs = await getSuggestions("a".repeat(64));
    expect(secs).toHaveLength(1);
    expect(secs[0].chips[0].text).toBe("A");
  } finally {
    g.fetch = real;
  }
});

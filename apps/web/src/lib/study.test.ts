import { describe, it, expect, vi, afterEach } from "vitest";
import { studyAndMix, type StudyStage } from "./study";

afterEach(() => vi.unstubAllGlobals());

const S1 = "a".repeat(64);
const S2 = "b".repeat(64);

/** Mock every endpoint as instantly ready, recording "METHOD url" call order. */
function mockAllReady(record: string[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, opts?: { method?: string }) => {
      const u = String(url);
      const method = opts?.method ?? "GET";
      record.push(`${method} ${u}`);
      if (u.includes("/stems")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            song_id: "x",
            status: "ready",
            stems: { vocals: "/v", drums: "/d", bass: "/b", other: "/o" },
          }),
        });
      }
      if (u.includes("/analysis")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            song_id: "x",
            status: "ready",
            bpm: 120,
            key: null,
            sections: [],
          }),
        });
      }
      if (u.endsWith("/mix") && method === "POST") {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            mix_id: "m",
            status: "ready",
            url: "/mix/m/audio",
            plan: null,
            message: null,
          }),
        });
      }
      return Promise.resolve({
        ok: false,
        json: async () => ({ detail: "?" }),
      });
    }),
  );
}

describe("studyAndMix", () => {
  it("emits the stages in order and returns the finished mix", async () => {
    const record: string[] = [];
    mockAllReady(record);
    const stages: StudyStage[] = [];
    const mix = await studyAndMix(S1, S2, (s) => stages.push(s), "", {
      pollMs: 0,
    });
    expect(stages).toEqual(["splitting", "analyzing", "planning", "done"]);
    expect(mix.mix_id).toBe("m");
  });

  it("splits BOTH songs before analyzing either — analysis reads the vocal stem", async () => {
    const record: string[] = [];
    mockAllReady(record);
    await studyAndMix(S1, S2, () => {}, "", { pollMs: 0 });

    const lastStem = record.reduce(
      (acc, r, i) => (r.includes("/stems") ? i : acc),
      -1,
    );
    const firstAnalysis = record.findIndex((r) => r.includes("/analysis"));
    expect(firstAnalysis).toBeGreaterThan(lastStem);
  });
});

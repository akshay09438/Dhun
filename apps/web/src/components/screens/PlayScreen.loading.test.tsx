import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { MixDTO, SongDTO } from "../../lib/api";

// A LivePlayer whose load() we can hold pending (mix still buffering) and then release.
const h = vi.hoisted(() => {
  let release: () => void = () => {};
  const load = vi.fn(
    () =>
      new Promise<void>((res) => {
        release = res;
      }),
  );
  return { load, dispose: vi.fn(), release: () => release() };
});

vi.mock("../../lib/liveAudio", () => ({
  LivePlayer: vi.fn().mockImplementation(() => ({
    load: h.load,
    dispose: h.dispose,
    duration: () => 0,
    songTime: () => 0,
    play: () => {},
    pause: () => {},
    seek: () => {},
    schedule: () => {},
  })),
}));

import PlayScreen from "./PlayScreen";

const songs: SongDTO[] = [
  {
    id: "a",
    original_name: "beat.wav",
    url: "/songs/a/audio",
    status: "ready",
  },
  { id: "b", original_name: "voc.wav", url: "/songs/b/audio", status: "ready" },
];
const mix = {
  mix_id: "m",
  status: "ready",
  url: "/mix/m/audio",
  plan: {
    master_bpm: 120,
    vocal_stretch: 1,
    anchor: 16,
    beat_breath: false,
    take: 1,
    placements: [
      { anchor: 16, vocal_src: [0, 12], beat_breath: false, fx: null },
    ],
    s1_vocal_regions: [],
    notes: "",
    source: "rules",
  },
  message: null,
} as MixDTO;

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ sections: [], bpm: 120, downbeats: [] }),
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows a 'Loading your mix…' pill while buffering, then clears it when ready", async () => {
  render(
    <PlayScreen
      songs={songs}
      mix={mix}
      mixId="m"
      mixName="Tere Ocean"
      regenerating={false}
      onRegenerate={() => {}}
      onExport={() => {}}
      onNextSong={() => {}}
    />,
  );

  // load() is still pending -> the buffering pill is shown so the user knows it's loading.
  expect(screen.getByTestId("mix-loading")).toBeTruthy();
  expect(screen.getByText(/loading your mix/i)).toBeTruthy();

  // Audio finishes loading -> the pill goes away.
  h.release();
  await waitFor(() => expect(screen.queryByTestId("mix-loading")).toBeNull());
});

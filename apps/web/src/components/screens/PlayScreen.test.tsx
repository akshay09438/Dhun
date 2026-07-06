import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import PlayScreen from "./PlayScreen";
import type { MixDTO, SongDTO } from "../../lib/api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

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

test("PlayScreen renders the mix name, four parts and Beat up (no Web Audio in jsdom)", () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ sections: [] }) }),
  );
  render(
    <PlayScreen
      songs={songs}
      mix={mix}
      mixId="m"
      mixName="Tere Ocean"
      regenerating={false}
      onRegenerate={() => {}}
      onExport={() => {}}
    />,
  );
  expect(screen.getAllByText(/tere ocean/i).length).toBeGreaterThan(0);
  expect(screen.getByTestId("beat-up")).toBeTruthy();
  ["drums", "bass", "other", "vocals"].forEach((b) =>
    expect(screen.getByTestId(`bus-${b}`)).toBeTruthy(),
  );
});

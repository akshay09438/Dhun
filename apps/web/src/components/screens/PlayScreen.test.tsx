import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { PlayMember } from "../../types";

// The Play screen plays ONE finished track now — mock that player so whenReady resolves.
vi.mock("../../lib/trackAudio", () => ({
  TrackPlayer: vi.fn().mockImplementation(() => ({
    whenReady: () => Promise.resolve(),
    on: () => {},
    play: () => {},
    pause: () => {},
    seek: () => {},
    currentTime: () => 0,
    duration: () => 100,
    dispose: () => {},
  })),
}));

import PlayScreen from "./PlayScreen";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const SOLO: PlayMember[] = [
  {
    index: 1,
    beat: "Father Ocean",
    vocal: "Tere Bina",
    kept: true,
    reason: null,
    seamAt: null,
  },
];

const TWO_SETS: PlayMember[] = [
  {
    index: 1,
    beat: "Father Ocean",
    vocal: "Tere Bina",
    kept: true,
    reason: null,
    seamAt: null,
  },
  {
    index: 2,
    beat: "Innerbloom",
    vocal: "Dooriyan",
    kept: true,
    reason: null,
    seamAt: 30,
  },
];

function renderPlay(over: Partial<Parameters<typeof PlayScreen>[0]> = {}) {
  return render(
    <PlayScreen
      title="Violet Undertow"
      audioUrl="/mix/m/audio"
      members={SOLO}
      regenerable={true}
      regenerating={false}
      onRegenerate={() => {}}
      onExport={() => {}}
      onNextSong={() => {}}
      {...over}
    />,
  );
}

test("renders the name and the line-up, with NO steering controls", () => {
  renderPlay();
  expect(screen.getAllByText(/violet undertow/i).length).toBeGreaterThan(0);
  expect(screen.getByTestId("set-lineup")).toBeTruthy();
  expect(screen.getByTestId("lineup-1")).toBeTruthy();

  // The live-steering controls are gone: no Parts, no chips, no type box.
  expect(screen.queryByTestId("beat-up")).toBeNull();
  ["drums", "bass", "other", "vocals"].forEach((b) =>
    expect(screen.queryByTestId(`bus-${b}`)).toBeNull(),
  );
  const { container } = renderPlay();
  expect(container.querySelector("input")).toBeNull(); // the "tell the mix…" box is gone
});

test("'Next song' returns to start a new mix", () => {
  const onNextSong = vi.fn();
  renderPlay({ onNextSong });
  fireEvent.click(screen.getByTestId("next-song"));
  expect(onNextSong).toHaveBeenCalledTimes(1);
});

test("a two-set line-up shows both sets back-to-back with a join marker", async () => {
  renderPlay({ members: TWO_SETS, regenerable: false });
  expect(screen.getByTestId("lineup-1")).toBeTruthy();
  expect(screen.getByTestId("lineup-2")).toBeTruthy();
  expect(screen.getByText(/back-to-back/i)).toBeTruthy();
  // The join marker appears once the track's duration is known (a microtask later).
  expect(await screen.findByTestId("seam-2")).toBeTruthy();
});

test("a dropped set shows its plain-language reason and is marked skipped", () => {
  const dropped: PlayMember[] = [
    {
      index: 1,
      beat: "Father Ocean",
      vocal: "Tere Bina",
      kept: true,
      reason: null,
      seamAt: null,
    },
    {
      index: 2,
      beat: "Innerbloom",
      vocal: "Dooriyan",
      kept: false,
      reason: "This pair is too far from the set's tempo to blend.",
      seamAt: null,
    },
  ];
  renderPlay({ members: dropped, regenerable: false });
  expect(screen.getByText(/too far from the set's tempo/i)).toBeTruthy();
  expect(screen.getByText(/skipped/i)).toBeTruthy();
});

test("'regenerate' shows for a single mix and hides for a set", () => {
  renderPlay({ regenerable: true });
  expect(screen.getByRole("button", { name: /regenerate/i })).toBeTruthy();
  cleanup();
  renderPlay({ members: TWO_SETS, regenerable: false });
  expect(screen.queryByRole("button", { name: /regenerate/i })).toBeNull();
});

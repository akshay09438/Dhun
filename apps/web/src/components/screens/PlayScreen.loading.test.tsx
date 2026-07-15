import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { PlayMember } from "../../types";

// A TrackPlayer whose whenReady() we hold pending (track buffering) then release.
const h = vi.hoisted(() => {
  let release: () => void = () => {};
  const whenReady = vi.fn(
    () =>
      new Promise<void>((res) => {
        release = res;
      }),
  );
  return { whenReady, release: () => release() };
});

vi.mock("../../lib/trackAudio", () => ({
  TrackPlayer: vi.fn().mockImplementation(() => ({
    whenReady: h.whenReady,
    on: () => {},
    play: () => {},
    pause: () => {},
    seek: () => {},
    currentTime: () => 0,
    duration: () => 0,
    dispose: () => {},
  })),
}));

import PlayScreen from "./PlayScreen";

const members: PlayMember[] = [
  {
    index: 1,
    beat: "Father Ocean",
    vocal: "Tere Bina",
    kept: true,
    reason: null,
    seamAt: null,
  },
];

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows a 'Loading your mix…' pill while buffering, then clears it when ready", async () => {
  render(
    <PlayScreen
      title="Tere Ocean"
      audioUrl="/mix/m/audio"
      members={members}
      regenerable={true}
      regenerating={false}
      onRegenerate={() => {}}
      onExport={() => {}}
      onNextSong={() => {}}
    />,
  );

  // whenReady() is still pending -> the buffering pill is shown.
  expect(screen.getByTestId("mix-loading")).toBeTruthy();
  expect(screen.getByText(/loading your mix/i)).toBeTruthy();

  // The track finishes loading -> the pill goes away.
  h.release();
  await waitFor(() => expect(screen.queryByTestId("mix-loading")).toBeNull());
});

import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import SetupScreen from "./SetupScreen";
import type { LibrarySongDTO } from "../../lib/api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const LIB = {
  songs: [
    {
      id: "a".repeat(64),
      original_name: "Father Ocean",
      url: "/songs/a/audio",
      status: "ready",
      role_hint: "beat",
    },
    {
      id: "c".repeat(64),
      original_name: "Rather Be",
      url: "/songs/c/audio",
      status: "ready",
      role_hint: "vocals",
    },
  ],
};

function noop() {}

function renderSetup(over: Partial<Parameters<typeof SetupScreen>[0]> = {}) {
  return render(
    <SetupScreen
      pick1={null}
      pick2={null}
      onPick1={noop}
      onPick2={noop}
      prompt=""
      onPrompt={noop}
      canMix={false}
      onMixIt={noop}
      {...over}
    />,
  );
}

test("clicking a song slot opens the catalog dropdown and picking calls back", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => LIB }),
  );
  const onPick1 = vi.fn();
  renderSetup({ onPick1 });

  fireEvent.click(screen.getByTestId("song-slot-1"));
  const option = await screen.findByRole("option", { name: /father ocean/i });
  fireEvent.click(option);

  expect(onPick1).toHaveBeenCalledTimes(1);
  expect((onPick1.mock.calls[0][0] as LibrarySongDTO).original_name).toBe(
    "Father Ocean",
  );
});

test("an empty library says so instead of showing a blank dropdown", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({ songs: [] }) }),
  );
  renderSetup();
  fireEvent.click(screen.getByTestId("song-slot-2"));
  expect(await screen.findByText(/no songs in the library/i)).toBeTruthy();
});

test("a failed library load shows a plain-language note", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
  renderSetup();
  fireEvent.click(screen.getByTestId("song-slot-1"));
  expect(await screen.findByText(/couldn.t load the songs/i)).toBeTruthy();
});

import {
  render,
  screen,
  fireEvent,
  cleanup,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import SetupScreen from "./SetupScreen";
import { MAX_MIXES_PER_SET, type SetPick } from "../../types";

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

function stubLibrary(lib: unknown = LIB) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => lib }),
  );
}

function renderSetup(onBuild: (sets: SetPick[]) => void = () => {}) {
  return render(<SetupScreen onBuild={onBuild} />);
}

/** Fill the currently-active set's two slots with the catalog's beat + vocal. */
async function fillActiveSet() {
  fireEvent.click(screen.getByTestId("song-slot-1"));
  fireEvent.click(await screen.findByRole("option", { name: /father ocean/i }));
  fireEvent.click(screen.getByTestId("song-slot-2"));
  fireEvent.click(await screen.findByRole("option", { name: /rather be/i }));
}

test("clicking a song slot opens the catalog dropdown and picking fills the slot", async () => {
  stubLibrary();
  renderSetup();

  fireEvent.click(screen.getByTestId("song-slot-1"));
  const option = await screen.findByRole("option", { name: /father ocean/i });
  fireEvent.click(option);

  // The chosen name now shows in the slot (state lives inside the screen now).
  expect(
    within(screen.getByTestId("song-slot-1")).getByText(/father ocean/i),
  ).toBeTruthy();
});

test("Song 1 offers only beats; Song 2 offers only vocals", async () => {
  stubLibrary();
  renderSetup();

  fireEvent.click(screen.getByTestId("song-slot-1"));
  expect(
    await screen.findByRole("option", { name: /father ocean/i }),
  ).toBeTruthy();
  expect(screen.queryByRole("option", { name: /rather be/i })).toBeNull();

  fireEvent.click(screen.getByTestId("song-slot-2"));
  expect(
    await screen.findByRole("option", { name: /rather be/i }),
  ).toBeTruthy();
  expect(screen.queryByRole("option", { name: /father ocean/i })).toBeNull();
});

test("no prompt box on the setup screen", () => {
  stubLibrary();
  const { container } = renderSetup();
  expect(container.querySelector("textarea")).toBeNull();
});

test("an empty library says so instead of showing a blank dropdown", async () => {
  stubLibrary({ songs: [] });
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

test("the primary button is disabled until both songs are picked, then builds one set", async () => {
  stubLibrary();
  const onBuild = vi.fn();
  renderSetup(onBuild);

  const btn = () =>
    screen.getByRole("button", { name: /mix it/i }) as HTMLButtonElement;
  expect(btn().disabled).toBe(true);

  await fillActiveSet();
  expect(btn().disabled).toBe(false);

  fireEvent.click(btn());
  expect(onBuild).toHaveBeenCalledTimes(1);
  const sets = onBuild.mock.calls[0][0] as SetPick[];
  expect(sets).toHaveLength(1);
  expect(sets[0].beat.original_name).toBe("Father Ocean");
  expect(sets[0].vocal.original_name).toBe("Rather Be");
});

test("'Add another set' is disabled until the first set is complete", async () => {
  stubLibrary();
  renderSetup();
  const add = () => screen.getByTestId("add-set") as HTMLButtonElement;
  expect(add().disabled).toBe(true);
  await fillActiveSet();
  expect(add().disabled).toBe(false);
});

test("adding a second mix shows a running order and switches the button to 'Build the set'", async () => {
  stubLibrary();
  renderSetup();

  await fillActiveSet();
  fireEvent.click(screen.getByTestId("add-set"));

  // Two cards in the running order; single-mix default is gone.
  expect(screen.getByTestId("set-card-1")).toBeTruthy();
  expect(screen.getByTestId("set-card-2")).toBeTruthy();
  expect(screen.getByRole("button", { name: /build the set/i })).toBeTruthy();

  // Under the cap, "Add another" is still offered (a set now holds up to MAX_MIXES_PER_SET).
  expect(screen.queryByTestId("add-set")).not.toBeNull();
});

test("the set line-up caps at MAX_MIXES_PER_SET mixes", async () => {
  stubLibrary();
  renderSetup();

  // Fill the first mix, then add + fill until the running order is full.
  await fillActiveSet();
  for (let n = 1; n < MAX_MIXES_PER_SET; n++) {
    fireEvent.click(screen.getByTestId("add-set"));
    await fillActiveSet(); // fills the newly-added (now active) mix
  }

  expect(screen.getByTestId(`set-card-${MAX_MIXES_PER_SET}`)).toBeTruthy();
  // At the cap the "Add another" control is gone.
  expect(screen.queryByTestId("add-set")).toBeNull();
});

test("removing the second set returns to the effortless single-set screen", async () => {
  stubLibrary();
  renderSetup();

  await fillActiveSet();
  fireEvent.click(screen.getByTestId("add-set"));
  expect(screen.getByTestId("running-order")).toBeTruthy();

  fireEvent.click(screen.getByTestId("remove-set-2"));
  expect(screen.queryByTestId("running-order")).toBeNull();
  expect(screen.getByRole("button", { name: /mix it/i })).toBeTruthy();
});

test("sets can only be added here — the note is present", () => {
  stubLibrary();
  renderSetup();
  expect(screen.getByText(/sets can only be added here/i)).toBeTruthy();
});

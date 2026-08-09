import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import ExportScreen from "./ExportScreen";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const AUDIO_PATH = "/mix/m/audio";

test("ExportScreen shows the name and downloads the full mix", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) });
  vi.stubGlobal("fetch", fetchMock);
  const u = URL as unknown as {
    createObjectURL: () => string;
    revokeObjectURL: () => void;
  };
  u.createObjectURL = vi.fn(() => "blob:x");
  u.revokeObjectURL = vi.fn();

  render(
    <ExportScreen
      audioPath={AUDIO_PATH}
      mixName="Tere Ocean"
      onStartOver={() => {}}
      onBack={() => {}}
    />,
  );

  expect(screen.getByText(/tere ocean/i)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /download full mix/i }));
  await Promise.resolve();
  expect(fetchMock).toHaveBeenCalled();
});

test("Download attaches the link to the page and keeps the file URL alive until the browser takes it", async () => {
  // Regression guard for the "clicking Download saves nothing" bug: the browser only
  // performs the save if (a) the <a> is actually in the document when clicked, and
  // (b) the object URL is still valid when the browser reads it — i.e. it must NOT be
  // revoked in the same synchronous tick as the click. Fake timers let us observe the
  // cleanup being deferred to a later task rather than running with the click.
  vi.useFakeTimers();
  const fetchMock = vi
    .fn()
    .mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) });
  vi.stubGlobal("fetch", fetchMock);
  const revokeSpy = vi.fn();
  const u = URL as unknown as {
    createObjectURL: () => string;
    revokeObjectURL: () => void;
  };
  u.createObjectURL = vi.fn(() => "blob:x");
  u.revokeObjectURL = revokeSpy;

  render(
    <ExportScreen
      audioPath={AUDIO_PATH}
      mixName="Tere Ocean"
      onStartOver={() => {}}
      onBack={() => {}}
    />,
  );

  // Capture the exact anchor the handler creates and spy its instance click, so we can
  // inspect whether it was attached to the DOM at the moment it was clicked.
  let clicked = false;
  let connectedAtClick: boolean | null = null;
  const realCreate = document.createElement.bind(document);
  vi.spyOn(document, "createElement").mockImplementation(((
    tag: string,
    opts?: ElementCreationOptions,
  ) => {
    const el = realCreate(tag as "a", opts);
    if (tag === "a") {
      vi.spyOn(el as HTMLAnchorElement, "click").mockImplementation(function (
        this: HTMLAnchorElement,
      ) {
        clicked = true;
        connectedAtClick = this.isConnected;
      });
    }
    return el;
  }) as typeof document.createElement);

  fireEvent.click(screen.getByRole("button", { name: /download full mix/i }));
  // Flush the fetch/blob microtasks so the handler reaches the click + schedules cleanup.
  for (let i = 0; i < 10; i++) await Promise.resolve();

  // (a) the link must be part of the page when it is clicked
  expect(clicked).toBe(true);
  expect(connectedAtClick).toBe(true);
  // (b) the file URL must NOT be revoked in the same tick as the click — otherwise the
  //     browser never gets to read the blob and nothing is saved. Cleanup is deferred.
  expect(revokeSpy).not.toHaveBeenCalled();

  // Once the browser has had its turn (a later task), the URL is cleaned up.
  vi.runAllTimers();
  expect(revokeSpy).toHaveBeenCalledTimes(1);

  vi.useRealTimers();
});

test("ExportScreen flags the clip export as coming soon", () => {
  vi.stubGlobal("fetch", vi.fn());
  render(
    <ExportScreen
      audioPath={AUDIO_PATH}
      mixName="Tere Ocean"
      onStartOver={() => {}}
      onBack={() => {}}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /14-second clip/i }));
  expect(screen.getByRole("status").textContent).toMatch(/coming soon/i);
});

import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import ExportScreen from "./ExportScreen";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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

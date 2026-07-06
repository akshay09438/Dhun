import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import LiveMix from "./LiveMix";
import * as api from "../../lib/api";

vi.mock("../../lib/liveAudio", () => ({
  LivePlayer: class {
    load = vi.fn().mockResolvedValue(undefined);
    play = vi.fn();
    pause = vi.fn();
    schedule = vi.fn();
    songTime = () => 0;
    dispose = vi.fn();
  },
}));

test("typing 'take the bass out' shows the DJ reply and flips the bass indicator off", async () => {
  vi.spyOn(api, "getLiveContext").mockResolvedValue({
    bpm: 120,
    downbeats: [0, 2, 4],
  });
  vi.spyOn(api, "postLiveCommand").mockResolvedValue({
    op: "mute",
    target: "bass",
    when: "next_bar",
    say: "dropping the bass on the next bar",
    reason: null,
  });

  render(<LiveMix song1Id={"a".repeat(64)} song2Id={"b".repeat(64)} />);
  fireEvent.change(screen.getByPlaceholderText(/take the bass out/i), {
    target: { value: "take the bass out" },
  });
  fireEvent.submit(screen.getByRole("form", { name: /command/i }));

  await waitFor(() =>
    expect(screen.getByText(/dropping the bass/i)).toBeTruthy(),
  );
  expect(screen.getByTestId("bus-bass").getAttribute("data-on")).toBe("false");
});

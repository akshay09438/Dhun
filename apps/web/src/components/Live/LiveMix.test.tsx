import { render, screen } from "@testing-library/react";
import LiveMix from "./LiveMix";

test("LiveMix shows the four part controls without crashing (no Web Audio in jsdom)", () => {
  render(<LiveMix song1Id={"a".repeat(64)} song2Id={"b".repeat(64)} />);
  expect(screen.getByText("Beat")).toBeTruthy();
  expect(screen.getByText("Bass")).toBeTruthy();
  expect(screen.getByText("Melody")).toBeTruthy();
  expect(screen.getByText("Vocals")).toBeTruthy();
  expect(screen.getByText("Beat up")).toBeTruthy(); // the energy move
});

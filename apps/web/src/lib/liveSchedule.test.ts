import { barSeconds, nextBarTime, applyOp, rampTarget } from "./liveSchedule";

test("barSeconds is one 4/4 bar", () => {
  expect(barSeconds(120)).toBeCloseTo(2.0);
});

test("nextBarTime picks the next real downbeat", () => {
  expect(nextBarTime([0, 2, 4, 6], 2.3, 120)).toBe(4);
});

test("nextBarTime falls back to bpm grid when no downbeats", () => {
  expect(nextBarTime([], 2.3, 120)).toBeCloseTo(4.0); // next 2s multiple after 2.3
});

test("applyOp mutes and unmutes the target bus only", () => {
  const s = { drums: true, bass: true, other: true };
  expect(applyOp(s, { op: "mute", target: "bass" })).toEqual({
    drums: true,
    bass: false,
    other: true,
  });
  expect(
    applyOp({ ...s, bass: false }, { op: "unmute", target: "bass" }).bass,
  ).toBe(true);
  expect(applyOp(s, { op: "decline", target: null })).toEqual(s);
});

test("rampTarget is 0 for mute, 1 for unmute", () => {
  expect(rampTarget({ op: "mute" })).toBe(0);
  expect(rampTarget({ op: "unmute" })).toBe(1);
});

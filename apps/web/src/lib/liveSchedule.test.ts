import {
  barSeconds,
  nextBarTime,
  applyOp,
  rampTarget,
  currentChips,
  type BusState,
  type Section,
} from "./liveSchedule";

test("beat_up leaves every part audible (all buses on — melody/vocals only duck)", () => {
  const muted: BusState = {
    drums: true,
    bass: true,
    other: false,
    vocals: false,
  };
  expect(applyOp(muted, { op: "beat_up" })).toEqual({
    drums: true,
    bass: true,
    other: true,
    vocals: true,
  });
});

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
  const s = { drums: true, bass: true, other: true, vocals: true };
  expect(applyOp(s, { op: "mute", target: "bass" })).toEqual({
    drums: true,
    bass: false,
    other: true,
    vocals: true,
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

test("applyOp flips every bus named in targets (combo)", () => {
  const s = { drums: true, bass: true, other: true, vocals: true };
  const r = applyOp(s, {
    op: "mute",
    target: null,
    targets: ["bass", "other", "vocals"],
  });
  expect(r).toEqual({ drums: true, bass: false, other: false, vocals: false });
});

test("applyOp unmutes all with a full targets list", () => {
  const s = { drums: false, bass: false, other: false, vocals: false };
  const r = applyOp(s, {
    op: "unmute",
    target: null,
    targets: ["drums", "bass", "other", "vocals"],
  });
  expect(r).toEqual({ drums: true, bass: true, other: true, vocals: true });
});

test("applyOp still honors a single target when targets is absent", () => {
  const s = { drums: true, bass: true, other: true, vocals: true };
  expect(applyOp(s, { op: "mute", target: "vocals" }).vocals).toBe(false);
});

test("applyOp treats a fade as all named buses off", () => {
  const s = { drums: true, bass: true, other: true, vocals: true };
  const r = applyOp(s, {
    op: "fade",
    target: null,
    targets: ["drums", "bass", "other", "vocals"],
  });
  expect(r).toEqual({ drums: false, bass: false, other: false, vocals: false });
});

test("currentChips picks the section the playhead is in", () => {
  const sections: Section[] = [
    {
      start: 0,
      end: 30,
      label: "intro",
      chips: [{ text: "A", op: "mute", targets: ["bass"] }],
    },
    {
      start: 30,
      end: 60,
      label: "chorus",
      chips: [{ text: "B", op: "unmute", targets: ["vocals"] }],
    },
  ];
  expect(currentChips(sections, 5).map((c) => c.text)).toEqual(["A"]);
  expect(currentChips(sections, 45).map((c) => c.text)).toEqual(["B"]);
  expect(currentChips(sections, 30).map((c) => c.text)).toEqual(["B"]); // boundary belongs to the new section
});

test("currentChips is empty for no sections", () => {
  expect(currentChips([], 10)).toEqual([]);
});

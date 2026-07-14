import {
  API_BASE,
  fetchVocalBus,
  type LiveOpDTO,
  type LiveContextDTO,
} from "./api";
import { barSeconds, busesOf, nextBarTime, type BusName } from "./liveSchedule";

const FADE_BARS = 4; // "fade away" ramps the whole mix out over four bars
// "Beat up" = the beat takes over: melody + vocals duck to this level so drums + bass
// drive. Only reduces gains (never boosts above 1) — clip-safe by construction.
const BEAT_UP_DUCK = 0.4;
const BEAT_UP_LEVELS: Record<BusName, number> = {
  drums: 1,
  bass: 1,
  other: BEAT_UP_DUCK,
  vocals: BEAT_UP_DUCK,
};

export class LivePlayer {
  private ctx = new AudioContext();
  private buffers = new Map<BusName, AudioBuffer>();
  private gains = new Map<BusName, GainNode>();
  private sources = new Map<BusName, AudioBufferSourceNode>();
  private startCtxTime = 0; // ctx.currentTime that maps to song position 0
  private offset = 0; // song position to (re)start from — updated by pause() and seek()
  private playing = false;

  /** (Re)start every bus playing from song position `from`, anchored at ctx time `at`. */
  private startSources(at: number, from: number): void {
    for (const src of this.sources.values()) {
      try {
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    this.sources.clear();
    this.startCtxTime = at - from;
    for (const [bus, buf] of this.buffers) {
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.gains.get(bus)!);
      src.start(at, Math.min(from, buf.duration));
      this.sources.set(bus, src);
    }
  }

  private addBus(bus: BusName, buf: AudioBuffer): void {
    this.buffers.set(bus, buf);
    const g = this.ctx.createGain();
    g.gain.value = 1;
    g.connect(this.ctx.destination);
    this.gains.set(bus, g);
  }

  /** Load Song 1's instrumental stems, plus (when a mix exists) its arranged-vocal bus. */
  async load(
    song1Id: string,
    stemBuses: BusName[],
    mixId?: string,
  ): Promise<void> {
    await Promise.all(
      stemBuses.map(async (bus) => {
        const res = await fetch(`${API_BASE}/songs/${song1Id}/stems/${bus}`);
        const buf = await this.ctx.decodeAudioData(await res.arrayBuffer());
        this.addBus(bus, buf);
      }),
    );
    if (mixId) {
      const buf = await this.ctx.decodeAudioData(await fetchVocalBus(mixId));
      this.addBus("vocals", buf);
    }
  }

  play(): void {
    if (this.playing) return;
    this.startSources(this.ctx.currentTime + 0.1, this.offset); // resume from where we paused
    this.ctx.resume();
    this.playing = true;
  }

  pause(): void {
    this.offset = this.songTime(); // freeze the position so play() resumes here
    for (const src of this.sources.values()) {
      try {
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    this.sources.clear();
    this.playing = false;
  }

  /** Jump to `t` seconds — click/drag the transport. Keeps playing if it was playing. */
  seek(t: number): void {
    const target = Math.max(0, Math.min(t, this.duration()));
    this.offset = target;
    if (this.playing) this.startSources(this.ctx.currentTime + 0.02, target);
  }

  songTime(): number {
    return this.playing
      ? Math.max(0, this.ctx.currentTime - this.startCtxTime)
      : this.offset;
  }

  /** Length of the mix (the longest loaded bus), for the transport readout. */
  duration(): number {
    let d = 0;
    for (const b of this.buffers.values()) d = Math.max(d, b.duration);
    return d;
  }

  /** Schedule a mute/unmute/fade on the next bar, ramped over 1 bar (or FADE_BARS for a
   *  fade), for every named bus. */
  schedule(op: LiveOpDTO, ctx: LiveContextDTO): void {
    if (
      op.op !== "mute" &&
      op.op !== "unmute" &&
      op.op !== "fade" &&
      op.op !== "beat_up"
    )
      return;
    const bpm = ctx.bpm ?? 120;
    const barSong = nextBarTime(ctx.downbeats, this.songTime(), bpm);
    const startCtx = this.startCtxTime + barSong; // song time -> ctx time
    const endCtx =
      startCtx + barSeconds(bpm) * (op.op === "fade" ? FADE_BARS : 1);

    // "Beat up" ramps every bus to its beat-up level (drums/bass full, tops ducked).
    if (op.op === "beat_up") {
      for (const [bus, g] of this.gains) {
        g.gain.cancelScheduledValues(startCtx);
        g.gain.setValueAtTime(g.gain.value, startCtx);
        g.gain.linearRampToValueAtTime(BEAT_UP_LEVELS[bus], endCtx);
      }
      return;
    }

    const target = op.op === "unmute" ? 1 : 0; // mute and fade both go to 0
    for (const bus of busesOf(op)) {
      const g = this.gains.get(bus);
      if (!g) continue;
      g.gain.cancelScheduledValues(startCtx);
      g.gain.setValueAtTime(g.gain.value, startCtx);
      g.gain.linearRampToValueAtTime(target, endCtx);
    }
  }

  dispose(): void {
    this.pause();
    this.ctx.close();
  }
}

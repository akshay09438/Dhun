import { API_BASE, type LiveOpDTO, type LiveContextDTO } from "./api";
import {
  barSeconds,
  nextBarTime,
  rampTarget,
  type BusName,
} from "./liveSchedule";

export class LivePlayer {
  private ctx = new AudioContext();
  private buffers = new Map<BusName, AudioBuffer>();
  private gains = new Map<BusName, GainNode>();
  private sources = new Map<BusName, AudioBufferSourceNode>();
  private startCtxTime = 0; // ctx.currentTime when playback (song time 0) began
  private playing = false;

  async load(song1Id: string, buses: BusName[]): Promise<void> {
    await Promise.all(
      buses.map(async (bus) => {
        const res = await fetch(`${API_BASE}/songs/${song1Id}/stems/${bus}`);
        const buf = await this.ctx.decodeAudioData(await res.arrayBuffer());
        this.buffers.set(bus, buf);
        const g = this.ctx.createGain();
        g.gain.value = 1;
        g.connect(this.ctx.destination);
        this.gains.set(bus, g);
      }),
    );
  }

  play(): void {
    if (this.playing) return;
    this.startCtxTime = this.ctx.currentTime + 0.1; // small lead so all sources start together
    for (const [bus, buf] of this.buffers) {
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.gains.get(bus)!);
      src.start(this.startCtxTime);
      this.sources.set(bus, src);
    }
    this.ctx.resume();
    this.playing = true;
  }

  pause(): void {
    for (const src of this.sources.values()) src.stop();
    this.sources.clear();
    this.playing = false;
  }

  songTime(): number {
    return Math.max(0, this.ctx.currentTime - this.startCtxTime);
  }

  /** Schedule a mute/unmute on the next bar, ramped smoothly over one bar. */
  schedule(op: LiveOpDTO, ctx: LiveContextDTO): void {
    if ((op.op !== "mute" && op.op !== "unmute") || !op.target) return;
    const g = this.gains.get(op.target as BusName);
    if (!g) return;
    const bpm = ctx.bpm ?? 120;
    const barSong = nextBarTime(ctx.downbeats, this.songTime(), bpm);
    const startCtx = this.startCtxTime + barSong; // song time -> ctx time
    const target = rampTarget(op);
    g.gain.cancelScheduledValues(startCtx);
    g.gain.setValueAtTime(g.gain.value, startCtx);
    g.gain.linearRampToValueAtTime(target, startCtx + barSeconds(bpm)); // smooth 1-bar fade
  }

  dispose(): void {
    this.pause();
    this.ctx.close();
  }
}

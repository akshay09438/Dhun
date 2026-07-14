/** A tiny player for ONE finished track — a rendered mix or a joined set WAV.
 *
 * The Play screen no longer steers stems live, so it just plays a single file:
 * play / pause / seek / read the clock. A thin wrapper over HTMLAudioElement so the
 * screen stays declarative and tests can mock it (like the old stem player).
 * Safe in a non-DOM/test environment: if `Audio` is unavailable it becomes a no-op. */
export class TrackPlayer {
  private el: HTMLAudioElement | null;

  constructor(url: string) {
    this.el = typeof Audio !== "undefined" ? new Audio(url) : null;
    if (this.el) this.el.preload = "auto";
  }

  /** Resolves once metadata (duration) is known — or immediately if there's no media element
   *  and never hangs on a load error. Mirrors the old player's load() so the buffering pill works. */
  whenReady(): Promise<void> {
    const el = this.el;
    if (!el) return Promise.resolve();
    if (el.readyState >= 1) return Promise.resolve(); // HAVE_METADATA
    return new Promise((resolve) => {
      el.addEventListener("loadedmetadata", () => resolve(), { once: true });
      el.addEventListener("error", () => resolve(), { once: true });
    });
  }

  on(event: keyof HTMLMediaElementEventMap, cb: () => void): void {
    this.el?.addEventListener(event, cb);
  }

  play(): void {
    // play() returns a promise that rejects if autoplay is blocked or (in jsdom) unimplemented.
    this.el?.play?.()?.catch(() => {});
  }

  pause(): void {
    this.el?.pause?.();
  }

  seek(t: number): void {
    if (this.el) this.el.currentTime = t;
  }

  currentTime(): number {
    return this.el?.currentTime ?? 0;
  }

  duration(): number {
    const d = this.el?.duration ?? 0;
    return Number.isFinite(d) ? d : 0;
  }

  dispose(): void {
    if (this.el) {
      this.el.pause?.();
      this.el.removeAttribute("src");
    }
    this.el = null;
  }
}

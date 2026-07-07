import { useEffect, useRef, type ReactNode } from "react";
import type { Screen } from "../../types";

const STEPS: { key: Screen; label: string }[] = [
  { key: "setup", label: "Setup" },
  { key: "generating", label: "Generating" },
  { key: "play", label: "Play" },
  { key: "export", label: "Export" },
];

/** The persistent app shell: a 1280×800 frame scaled to fit the window, with the
 *  top bar (wordmark + a passive progress indicator). Screens fill the body. */
export default function Frame({
  screen,
  children,
}: {
  screen: Screen;
  children: ReactNode;
}) {
  const scaler = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fit = () => {
      const s = Math.min(window.innerWidth / 1280, window.innerHeight / 800, 1);
      scaler.current?.style.setProperty("--s", String(s));
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  return (
    <div className="pageWrap">
      <div className="scaler" ref={scaler}>
        <div className="frame">
          <header className="topbar">
            <div className="wordmark">
              <span className="dot" />
              PROMPT · DJ
            </div>
            <nav className="steps-nav" aria-label="Progress">
              {STEPS.map((s) => (
                <span key={s.key} className={s.key === screen ? "active" : ""}>
                  {s.label}
                </span>
              ))}
            </nav>
          </header>
          <div className="body" data-screen={screen}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

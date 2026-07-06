import { useState } from "react";
import { API_BASE, type MixDTO } from "../../lib/api";
import styles from "./ExportScreen.module.css";

export default function ExportScreen({
  mix,
  mixName,
  onStartOver,
  onBack,
}: {
  mix: MixDTO;
  mixName: string;
  onStartOver: () => void;
  onBack: () => void;
}) {
  const [note, setNote] = useState("");

  async function handleDownload() {
    if (!mix.url) return;
    const res = await fetch(`${API_BASE}${mix.url}`);
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `${(mixName || "prompt-dj-mix").replace(/[^\w -]/g, "").trim() || "prompt-dj-mix"}.wav`;
    a.click();
    URL.revokeObjectURL(href);
  }

  return (
    <>
      <div className="console">
        <p className="kicker">Export</p>
        <h1 className="title">Share your mix</h1>
        <p className={styles.explain}>
          {mixName ? <strong>{mixName}</strong> : "Your mix"} — download the
          full track now. A short shareable clip is on the way.
        </p>

        <button className="btnPrimary" onClick={handleDownload}>
          Download full mix
        </button>
        <button
          className="btnSecondary"
          onClick={() => setNote("Short-clip export is coming soon.")}
        >
          Export 14-second clip
        </button>

        <div className={styles.links}>
          <div
            className={styles.linkrow}
            onClick={() => setNote("Sharing links are coming soon.")}
          >
            Copy link <span className={styles.arr}>↗</span>
          </div>
          <div
            className={styles.linkrow}
            onClick={() => setNote("Posting is coming soon.")}
          >
            Post <span className={styles.arr}>↗</span>
          </div>
        </div>

        {note && (
          <p className={styles.note} role="status">
            {note}
          </p>
        )}

        <div className={styles.footerLinks}>
          <button className={styles.textLink} onClick={onBack}>
            ← back to the mix
          </button>
          <button className={styles.textLink} onClick={onStartOver}>
            start a new mix →
          </button>
        </div>
      </div>

      <div className="stage">
        <div className={styles.stageMid}>
          <div className={styles.clipLabel}>CLIP · DROP → VOCAL</div>
          <div className={styles.clip} role="img" aria-label="Clip waveform">
            {Array.from({ length: 46 }).map((_, i) => (
              <span
                key={i}
                style={{ height: `${20 + Math.abs(Math.sin(i / 2.2)) * 75}%` }}
              />
            ))}
          </div>
          <div className={styles.clipTimes}>
            <span>0:00</span>
            <span>0:14</span>
          </div>
        </div>
      </div>
    </>
  );
}

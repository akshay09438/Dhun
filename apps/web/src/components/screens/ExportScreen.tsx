import { useState } from "react";
import { API_BASE } from "../../lib/api";
import styles from "./ExportScreen.module.css";

export default function ExportScreen({
  audioPath,
  mixName,
  onStartOver,
  onBack,
}: {
  audioPath: string; // the finished track's URL path (a mix or a set)
  mixName: string;
  onStartOver: () => void;
  onBack: () => void;
}) {
  const [note, setNote] = useState("");

  async function handleDownload() {
    if (!audioPath) return;
    const res = await fetch(`${API_BASE}${audioPath}`);
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `${(mixName || "prompt-dj-mix").replace(/[^\w -]/g, "").trim() || "prompt-dj-mix"}.wav`;
    // The link must be in the document for the click to trigger a save in every browser
    // (a detached <a>.click() is ignored by some). And the object URL must stay valid
    // until the browser has read the blob — revoking it in the same tick as the click
    // cancels the download (the "saves nothing" bug), so defer the cleanup.
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(href);
      a.remove();
    }, 0);
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

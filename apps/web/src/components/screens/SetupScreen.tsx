import styles from "./SetupScreen.module.css";

export default function SetupScreen({
  file1,
  file2,
  onPick1,
  onPick2,
  prompt,
  onPrompt,
  canMix,
  onMixIt,
}: {
  file1: File | null;
  file2: File | null;
  onPick1: (f: File | null) => void;
  onPick2: (f: File | null) => void;
  prompt: string;
  onPrompt: (v: string) => void;
  canMix: boolean;
  onMixIt: () => void;
}) {
  return (
    <>
      <div className="console">
        <p className="kicker">New mix</p>
        <h1 className="title">Describe your mix</h1>

        <UploadCard
          n={1}
          file={file1}
          placeholder="Song One"
          role="→ its beat"
          onPick={onPick1}
        />
        <UploadCard
          n={2}
          file={file2}
          placeholder="Song Two"
          role="→ its vocals"
          onPick={onPick2}
        />

        <textarea
          className={styles.prompt}
          value={prompt}
          onChange={(e) => onPrompt(e.target.value)}
          rows={2}
          aria-label="Describe your mix"
        />

        <button className="btnPrimary" disabled={!canMix} onClick={onMixIt}>
          Mix it&nbsp;&nbsp;▸
        </button>
      </div>

      <div className="stage">
        <div className={styles.tiles}>
          <Tile label={file1 ? file1.name : "SONG 1"} />
          <span className={styles.tilePlus}>＋</span>
          <Tile label={file2 ? file2.name : "SONG 2"} />
        </div>
        <p className={styles.tagline}>
          Two songs in.
          <br />
          One mix out — arranged like a DJ.
        </p>
      </div>
    </>
  );
}

function UploadCard({
  n,
  file,
  placeholder,
  role,
  onPick,
}: {
  n: number;
  file: File | null;
  placeholder: string;
  role: string;
  onPick: (f: File | null) => void;
}) {
  return (
    <label className={styles.upload}>
      <span className={styles.plus}>{file ? "↺" : "+"}</span>
      <span className={styles.badge}>{n}</span>
      <span className={styles.songName} title={file?.name}>
        {file ? file.name : placeholder}
      </span>
      <span className={styles.role}>{role}</span>
      <input
        className={styles.fileInput}
        type="file"
        accept="audio/*"
        aria-label={`Choose ${placeholder}`}
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
      />
    </label>
  );
}

function Tile({ label }: { label: string }) {
  return (
    <div className={styles.tile} title={label}>
      {label}
    </div>
  );
}

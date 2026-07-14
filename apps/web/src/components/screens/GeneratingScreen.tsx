import { STUDY_STEPS, type StudyStage } from "../../lib/study";
import styles from "./GeneratingScreen.module.css";

export default function GeneratingScreen({
  stage,
  error,
  onStartOver,
}: {
  stage: StudyStage;
  error: string;
  onStartOver: () => void;
}) {
  const current = STUDY_STEPS.findIndex((s) => s.stage === stage);
  const pct =
    error || current < 0
      ? 100
      : Math.round(((current + 0.5) / STUDY_STEPS.length) * 100);
  const statusLabel = STUDY_STEPS[current]?.label ?? "Working";

  return (
    <>
      <div className="console">
        <p className="kicker">Arranging</p>
        <h1 className="title">Building your mix</h1>

        {error ? (
          <div className={styles.errorBox}>
            <p className="errorText" role="alert">
              {error}
            </p>
            <button className="btnSecondary" onClick={onStartOver}>
              Start over
            </button>
          </div>
        ) : (
          <ol className={styles.steps}>
            {STUDY_STEPS.map((step, i) => {
              const done = i < current;
              const active = i === current;
              const cls = done
                ? `${styles.step} ${styles.done}`
                : active
                  ? `${styles.step} ${styles.active}`
                  : styles.step;
              return (
                <li key={step.stage} className={cls}>
                  <span className={styles.ic} aria-hidden="true">
                    {done ? "✓" : active ? "…" : "·"}
                  </span>
                  {step.label}
                </li>
              );
            })}
          </ol>
        )}
      </div>

      <div className={`stage ${styles.genStage}`}>
        {!error && (
          <>
            <div className={styles.ring}>
              <div className={styles.core} />
            </div>
            <div className={styles.progress}>
              <i style={{ width: `${pct}%` }} />
            </div>
            <div className={styles.status}>{statusLabel}</div>
          </>
        )}
      </div>
    </>
  );
}

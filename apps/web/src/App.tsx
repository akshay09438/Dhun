import { useState } from "react";
import {
  API_BASE,
  getMixName,
  makeMix,
  type MixDTO,
  type SetDTO,
} from "./lib/api";
import { studyAndBuildSet, studyAndMix, type StudyStage } from "./lib/study";
import type { PlayMember, Screen, SetPick } from "./types";
import Frame from "./components/shell/Frame";
import SetupScreen from "./components/screens/SetupScreen";
import GeneratingScreen from "./components/screens/GeneratingScreen";
import PlayScreen from "./components/screens/PlayScreen";
import ExportScreen from "./components/screens/ExportScreen";

// The setup prompt box was removed (it steered nothing at mix time). Mixes use an empty prompt.
const MIX_PROMPT = "";

export function App() {
  const [screen, setScreen] = useState<Screen>("setup");
  const [sets, setSets] = useState<SetPick[]>([]); // the chosen line-up (for names + regenerate)
  const [mix, setMix] = useState<MixDTO | null>(null); // single-set path
  const [setInfo, setSetInfo] = useState<SetDTO | null>(null); // two-set path
  const [name, setName] = useState(""); // the mix or set's playful name
  const [stage, setStage] = useState<StudyStage>("uploading");
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState("");

  const isSet = setInfo !== null;
  const audioPath = isSet ? setInfo?.url : mix?.url;

  /** The Play screen's line-up: one row per set, with the songs and (for a set) the drops. */
  const members: PlayMember[] = isSet
    ? (setInfo?.members ?? []).map((m) => {
        const pick = sets[m.index - 1];
        return {
          index: m.index,
          beat: pick?.beat.original_name ?? "Song 1",
          vocal: pick?.vocal.original_name ?? "Song 2",
          kept: m.kept,
          reason: m.reason,
          seamAt: m.seam_at,
        };
      })
    : sets[0]
      ? [
          {
            index: 1,
            beat: sets[0].beat.original_name,
            vocal: sets[0].vocal.original_name,
            kept: true,
            reason: null,
            seamAt: null,
          },
        ]
      : [];

  /** Name a single mix (fallback-safe; never blocks the UI). */
  function loadName(s1: string, s2: string) {
    setName("");
    getMixName(s1, s2, MIX_PROMPT)
      .then(setName)
      .catch(() => setName(""));
  }

  /** Build the chosen line-up: one set → a single mix; two sets → the continuous set builder.
   *  Best-parts (gated) always runs through the set builder — where the crop+arc lives — so a single
   *  pair with best-parts on becomes a one-mix best-parts "set" (its own ~3-min highlight). */
  async function handleBuild(picks: SetPick[], bestParts = false) {
    setError("");
    setSets(picks);
    setScreen("generating");
    setStage("uploading");

    if (picks.length === 1 && !bestParts) {
      const { beat, vocal } = picks[0];
      setSetInfo(null);
      try {
        const made = await studyAndMix(beat.id, vocal.id, setStage, MIX_PROMPT);
        setMix(made);
        loadName(beat.original_name, vocal.original_name);
        setScreen("play");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Something went wrong.");
      }
      return;
    }

    setMix(null);
    try {
      const built = await studyAndBuildSet(picks, setStage, {}, bestParts);
      setSetInfo(built);
      loadName(
        picks[0].beat.original_name,
        picks[picks.length - 1].vocal.original_name,
      );
      setScreen("play");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't build your set.");
    }
  }

  /** Regenerate a fresh take of a single mix without leaving the Play screen. */
  async function handleRegenerate() {
    if (isSet || sets.length < 1 || regenerating) return;
    const take = (mix?.plan?.take ?? 1) + 1;
    setRegenerating(true);
    try {
      const made = await makeMix(
        sets[0].beat.id,
        sets[0].vocal.id,
        MIX_PROMPT,
        take,
      );
      setMix(made);
    } catch {
      /* keep the current take on failure */
    } finally {
      setRegenerating(false);
    }
  }

  /** Back to Setup, ready for a new line-up. */
  function startOver() {
    setScreen("setup");
    setError("");
    setSets([]);
    setMix(null);
    setSetInfo(null);
    setName("");
  }

  return (
    <Frame screen={screen}>
      {screen === "setup" && <SetupScreen onBuild={handleBuild} />}
      {screen === "generating" && (
        <GeneratingScreen stage={stage} error={error} onStartOver={startOver} />
      )}
      {screen === "play" && audioPath && members.length > 0 && (
        <PlayScreen
          title={name}
          audioUrl={`${API_BASE}${audioPath}`}
          members={members}
          regenerable={!isSet}
          regenerating={regenerating}
          onRegenerate={handleRegenerate}
          onExport={() => setScreen("export")}
          onNextSong={startOver}
        />
      )}
      {screen === "export" && audioPath && (
        <ExportScreen
          audioPath={audioPath}
          mixName={name}
          onStartOver={startOver}
          onBack={() => setScreen("play")}
        />
      )}
    </Frame>
  );
}

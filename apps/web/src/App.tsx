import { useState } from "react";
import {
  getMixName,
  makeMix,
  type LibrarySongDTO,
  type MixDTO,
  type SongDTO,
} from "./lib/api";
import { studyAndMix, type StudyStage } from "./lib/study";
import type { Screen } from "./types";
import Frame from "./components/shell/Frame";
import SetupScreen from "./components/screens/SetupScreen";
import GeneratingScreen from "./components/screens/GeneratingScreen";
import PlayScreen from "./components/screens/PlayScreen";
import ExportScreen from "./components/screens/ExportScreen";

const DEFAULT_PROMPT = "Song 1's beat, Song 2's vocals — mixed like a DJ";

export function App() {
  const [screen, setScreen] = useState<Screen>("setup");
  const [pick1, setPick1] = useState<LibrarySongDTO | null>(null);
  const [pick2, setPick2] = useState<LibrarySongDTO | null>(null);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [songs, setSongs] = useState<SongDTO[]>([]);
  const [mix, setMix] = useState<MixDTO | null>(null);
  const [mixId, setMixId] = useState<string | undefined>(undefined);
  const [mixName, setMixName] = useState("");
  const [stage, setStage] = useState<StudyStage>("uploading");
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState("");

  /** Fetch a playful AI name for the mix (fallback-safe; never blocks the UI). */
  function loadName(s1: SongDTO, s2: SongDTO) {
    setMixName("");
    getMixName(s1.original_name, s2.original_name, prompt)
      .then(setMixName)
      .catch(() => setMixName(""));
  }

  async function handleMixIt() {
    if (!pick1 || !pick2) return;
    setScreen("generating");
    setStage("uploading");
    setError("");
    try {
      // Catalog songs are already ingested — no upload; go straight to the study.
      const chosen: SongDTO[] = [pick1, pick2];
      setSongs(chosen);
      const made = await studyAndMix(pick1.id, pick2.id, setStage, prompt);
      setMix(made);
      setMixId(made.mix_id);
      loadName(pick1, pick2);
      setScreen("play");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    }
  }

  /** Regenerate a fresh take without leaving the Play screen. */
  async function handleRegenerate() {
    if (songs.length < 2 || regenerating) return;
    const take = (mix?.plan?.take ?? 1) + 1;
    setRegenerating(true);
    try {
      const made = await makeMix(songs[0].id, songs[1].id, prompt, take);
      setMix(made);
      setMixId(made.mix_id);
    } catch {
      /* keep the current take on failure */
    } finally {
      setRegenerating(false);
    }
  }

  /** Back to Setup with empty song slots, ready for a new pair. */
  function startOver() {
    setScreen("setup");
    setError("");
    setPick1(null);
    setPick2(null);
    setSongs([]);
    setMix(null);
    setMixId(undefined);
    setMixName("");
  }

  return (
    <Frame screen={screen}>
      {screen === "setup" && (
        <SetupScreen
          pick1={pick1}
          pick2={pick2}
          onPick1={setPick1}
          onPick2={setPick2}
          prompt={prompt}
          onPrompt={setPrompt}
          canMix={Boolean(pick1) && Boolean(pick2)}
          onMixIt={handleMixIt}
        />
      )}
      {screen === "generating" && (
        <GeneratingScreen stage={stage} error={error} onStartOver={startOver} />
      )}
      {screen === "play" && mix && songs.length === 2 && (
        <PlayScreen
          songs={songs}
          mix={mix}
          mixId={mixId}
          mixName={mixName}
          regenerating={regenerating}
          onRegenerate={handleRegenerate}
          onExport={() => setScreen("export")}
          onNextSong={startOver}
        />
      )}
      {screen === "export" && mix && (
        <ExportScreen
          mix={mix}
          mixName={mixName}
          onStartOver={startOver}
          onBack={() => setScreen("play")}
        />
      )}
    </Frame>
  );
}

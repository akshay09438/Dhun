import { useState } from "react";
import {
  getMixName,
  makeMix,
  uploadSongs,
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
  const [file1, setFile1] = useState<File | null>(null);
  const [file2, setFile2] = useState<File | null>(null);
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
    if (!file1 || !file2) return;
    setScreen("generating");
    setStage("uploading");
    setError("");
    try {
      const res = await uploadSongs(file1, file2);
      setSongs(res.songs);
      const made = await studyAndMix(
        res.songs[0].id,
        res.songs[1].id,
        setStage,
        prompt,
      );
      setMix(made);
      setMixId(made.mix_id);
      loadName(res.songs[0], res.songs[1]);
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

  function startOver() {
    setScreen("setup");
    setError("");
    setSongs([]);
    setMix(null);
    setMixId(undefined);
    setMixName("");
  }

  return (
    <Frame screen={screen}>
      {screen === "setup" && (
        <SetupScreen
          file1={file1}
          file2={file2}
          onPick1={setFile1}
          onPick2={setFile2}
          prompt={prompt}
          onPrompt={setPrompt}
          canMix={Boolean(file1) && Boolean(file2)}
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

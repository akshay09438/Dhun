// Prompt-DJ pitch helper — offline Signalsmith Stretch (MIT) run headless via OfflineAudioContext.
// Validation-grade (swap for a native binding before scale). Deterministic within a launch; the Python
// wrapper (app/audio/pitch.py) still verifies two independent runs agree, AND the referee (validate.py)
// independently re-checks the shifted vocal's chroma — consistency is not correctness.
// Usage: node bridge.mjs --jobs jobs.json   (jobs = [{ id, in, out, sr, ch, semitones, rate, formant, ... }])
import http from "http";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import puppeteer from "puppeteer-core";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Chromium executable: $PITCH_CHROME wins; else any puppeteer-cached Chrome build; else system Edge. Portable.
function resolveChrome() {
  if (process.env.PITCH_CHROME && fs.existsSync(process.env.PITCH_CHROME))
    return process.env.PITCH_CHROME;
  const home = process.env.USERPROFILE || process.env.HOME || "";
  const cands = [];
  try {
    const dir = path.join(home, ".cache", "puppeteer", "chrome");
    for (const b of fs.readdirSync(dir)) {
      for (const exe of [
        path.join(dir, b, "chrome-win64", "chrome.exe"),
        path.join(dir, b, "chrome-linux64", "chrome"),
      ]) {
        if (fs.existsSync(exe)) cands.push(exe);
      }
    }
  } catch {
    /* no puppeteer cache */
  }
  cands.push(
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
  );
  for (const c of cands) if (fs.existsSync(c)) return c;
  throw new Error(
    "pitch helper: no Chromium found; set PITCH_CHROME to a Chromium/Edge executable",
  );
}
const CHROME = resolveChrome();

function arg(name, def) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : def;
}
const jobs = JSON.parse(fs.readFileSync(arg("jobs"), "utf8"));
for (const j of jobs) {
  j.bytes = fs.readFileSync(j.in);
  j.frames = Math.floor(j.bytes.length / 4 / j.ch);
}
const byId = Object.fromEntries(jobs.map((j) => [String(j.id), j]));

let resolveDone, rejectDone;
const done = new Promise((res, rej) => {
  resolveDone = res;
  rejectDone = rej;
});

const server = http.createServer((req, res) => {
  const url = req.url.split("?")[0];
  const mIn = url.match(/^\/in\/(.+)\.f32$/);
  const mOut = url.match(/^\/out\/(.+)\.f32$/);
  if (req.method === "GET" && url === "/jobs.json") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify(
        jobs.map((j) => ({
          id: String(j.id),
          sr: j.sr,
          ch: j.ch,
          frames: j.frames,
          semitones: j.semitones,
          rate: j.rate,
          formant: j.formant ? 1 : 0,
          formantBaseHz: j.formantBaseHz || 0,
          pad: j.pad ?? 1.0,
        })),
      ),
    );
    return;
  }
  if (req.method === "GET" && (url === "/" || url === "/index.html")) {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(fs.readFileSync(path.join(__dirname, "index.html")));
    return;
  }
  if (req.method === "GET" && url === "/SignalsmithStretch.mjs") {
    res.writeHead(200, { "Content-Type": "text/javascript" });
    res.end(
      fs.readFileSync(
        path.join(
          __dirname,
          "node_modules/signalsmith-stretch/SignalsmithStretch.mjs",
        ),
      ),
    );
    return;
  }
  if (req.method === "GET" && mIn) {
    const j = byId[mIn[1]];
    if (!j) {
      res.writeHead(404);
      res.end();
      return;
    }
    res.writeHead(200, { "Content-Type": "application/octet-stream" });
    res.end(j.bytes);
    return;
  }
  if (req.method === "POST" && mOut) {
    const j = byId[mOut[1]];
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      fs.writeFileSync(j.out, Buffer.concat(chunks));
      res.writeHead(200);
      res.end("ok");
    });
    return;
  }
  if (req.method === "POST" && url === "/alldone") {
    res.writeHead(200);
    res.end("ok");
    resolveDone();
    return;
  }
  if (req.method === "POST" && url === "/error") {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      res.writeHead(200);
      res.end("ok");
      rejectDone(new Error("page: " + Buffer.concat(chunks).toString()));
    });
    return;
  }
  res.writeHead(404);
  res.end("nf");
});

const port = await new Promise((r) =>
  server.listen(0, "127.0.0.1", () => r(server.address().port)),
);
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "shell",
  args: [
    "--no-sandbox",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-gpu",
  ],
});
try {
  const page = await browser.newPage();
  page.on("console", (m) => {
    const t = m.text();
    if (t.startsWith("ERR ") || t.startsWith("job ") || t.startsWith("batch"))
      console.log(t);
  });
  await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: "load" });
  await Promise.race([
    done,
    new Promise((_, rej) =>
      setTimeout(() => rej(new Error("timeout 600s")), 600000),
    ),
  ]);
  console.log(`OK ${jobs.length} jobs done`);
} catch (e) {
  console.error("FAIL " + (e.message || e));
  process.exitCode = 1;
} finally {
  try {
    await Promise.race([
      browser.close(),
      new Promise((r) => setTimeout(r, 4000)),
    ]);
  } catch {}
  server.close();
  process.exit(process.exitCode || 0);
}

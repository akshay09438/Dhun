@echo off
REM ============================================================================
REM  Start Prompt-DJ  —  double-click this to put your shareable link online.
REM
REM  It runs completely on its own (independent of Claude Code): as long as THIS
REM  window stays open and your PC is on, the public link works. Close this
REM  window to take the link offline.
REM
REM  Two windows will open:
REM    1) "Prompt-DJ engine"  — the mixing brain (leave it running)
REM    2) this window becomes the ngrok tunnel — it prints your public link
REM       on the "Forwarding" line (looks like https://xxxx.ngrok-free.app).
REM ============================================================================

title Prompt-DJ  (keep this window open to keep your link live)
cd /d "%~dp0"

echo.
echo  [1/3] Building the latest web app...
call npm -w apps/web run build
if errorlevel 1 echo  (build skipped/failed - will serve the last built version)

echo.
echo  [2/3] Starting the Prompt-DJ engine on port 8000...
start "Prompt-DJ engine" "services\api\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir "services\api" --port 8000

echo  Waiting for the engine to warm up...
timeout /t 4 >nul

echo.
echo  [3/3] Opening your public link (ngrok)...
echo  ----------------------------------------------------------------------
echo   Your shareable link appears below on the "Forwarding" line.
echo   Send that https://... address to your testers.
echo   Keep this window open. Close it to take the link offline.
echo  ----------------------------------------------------------------------
echo.

REM If you claim your free permanent ngrok domain, change the next line to:
REM   ngrok http --url=YOUR-NAME.ngrok-free.app 8000
ngrok http 8000

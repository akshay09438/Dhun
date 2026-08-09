@echo off
REM ============================================================================
REM  Start-Grinder  —  bring the Grinder Discord bot online.
REM
REM  Keep this window open while you demo. Two things run:
REM    1) "Prompt-DJ engine"  — the mixing brain on port 8000 (its own window)
REM    2) this window          — the Grinder bot, connected to Discord
REM  Close this window to take Grinder offline.
REM
REM  First run only: this creates the bot's Python environment and installs its
REM  packages (takes a minute). After that it starts instantly.
REM ============================================================================
title Grinder  (keep this window open to keep the bot online)
cd /d "%~dp0"

if not exist "services\discord-bot\.env" (
  echo.
  echo   No token found. Run Set-Grinder-Token.bat first, then start again.
  echo.
  pause
  exit /b 1
)

echo.
echo  [1/3] Starting the Prompt-DJ engine on port 8000...
start "Prompt-DJ engine" "services\api\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir "services\api" --port 8000
echo  Waiting for the engine to warm up...
timeout /t 5 >nul

cd services\discord-bot
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  [2/3] First run: creating the bot environment and installing packages...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  echo  Installing voice support (best-effort)...
  ".venv\Scripts\python.exe" -m pip install --quiet PyNaCl
) else (
  echo  [2/3] Bot environment ready.
)

echo.
echo  [3/3] Connecting Grinder to Discord...
echo  ----------------------------------------------------------------------
echo   When you see "logged in as Grinder", go to your Discord server and
echo   type  /mix  — pick a beat and a vocal, and the mix comes right back.
echo   Keep this window open. Close it to take Grinder offline.
echo  ----------------------------------------------------------------------
echo.
".venv\Scripts\python.exe" bot.py
pause

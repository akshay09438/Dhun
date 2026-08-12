@echo off
REM ============================================================================
REM  Start-Grinder  -  bring the Grinder Discord bot online.
REM
REM  Keep this window open while you demo. Two things run:
REM    1) "Prompt-DJ engine"  - the mixing brain on port 8000 (its own window)
REM    2) this window          - the Grinder bot, connected to Discord
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
REM Reuse an engine that's already up instead of starting a second one on a busy port.
>nul 2>nul powershell -NoProfile -Command "try { (New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',8000); exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo  [1/3] Starting the Prompt-DJ engine on port 8000...
  start "Prompt-DJ engine" "services\api\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir "services\api" --port 8000
  echo  Waiting for the engine to warm up...
  REM NOT `timeout` here: timeout needs a console input handle, so it dies with a parse-looking
  REM error ("... was unexpected at this time") when this file is run from PowerShell instead of
  REM being double-clicked. `ping` waits just as well and never touches stdin.
  ping -n 6 127.0.0.1 >nul
) else (
  echo  [1/3] Engine already running on port 8000 - reusing it.
)

cd services\discord-bot
REM ---------------------------------------------------------------------------
REM  WHICH ENVIRONMENT, AND WHY IT MATTERS (2026-08-12).
REM  Playing audio in a voice room needs the `davey` library, and davey ships NO
REM  build for ARM Windows - which is why Grinder could never make a sound on
REM  this machine. It DOES ship an Intel build, and Windows 11 on ARM runs Intel
REM  programs by emulation, so an Intel Python can install it and voice works.
REM  Proven on 2026-08-12: connected to a room and played audio.
REM  So: prefer .venv-x64 (Intel, voice works). Fall back to .venv (ARM, no voice
REM  but everything else fine) so this can never be worse than it was.
REM ---------------------------------------------------------------------------
set "BOTPY=.venv\Scripts\python.exe"
if exist ".venv-x64\Scripts\python.exe" (
  set "BOTPY=.venv-x64\Scripts\python.exe"
  echo  [2/3] Bot environment ready ^(Intel build - voice works^).
) else (
  if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  [2/3] First run: creating the bot environment and installing packages...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
    REM Parentheses MUST be escaped as ^( ^) inside an if/else block. cmd parses the whole
    REM block before running any of it, so a bare ) here kills the launcher outright - even
    REM though this branch never runs on a machine that already has a venv. That is exactly
    REM how this file silently stopped starting the bot on 2026-08-12.
    echo  Installing voice support ^(best-effort^)...
    ".venv\Scripts\python.exe" -m pip install --quiet PyNaCl
  ) else (
    echo  [2/3] Bot environment ready ^(ARM build - grinds work, voice will not^).
  )
)

REM  ONE GRINDER ON SHIFT AT A TIME. Closing a console window does not always stop the program
REM  behind it - on 2026-08-12 a Grinder from 18:34 was still running invisibly, and the new one
REM  ended up racing it: music started on its own, commands timed out, and a bot that knew nothing
REM  about the second room answered as if it were the only one. An hour went into chasing bugs that
REM  were not there. Clearing the shift first costs a second.
powershell -NoProfile -ExecutionPolicy Bypass -File "services\discord-bot\scripts\Stop-Other-Grinders.ps1"

echo.
echo  [3/3] Connecting Grinder to Discord...
echo  ----------------------------------------------------------------------
echo   When you see "logged in as Grinder", go to your Discord server and
echo   type  /grind  - pick a beat and a vocal, and the mix comes right back.
echo   Keep this window open. Close it to take Grinder offline.
echo  ----------------------------------------------------------------------
echo.
"%BOTPY%" bot.py
pause

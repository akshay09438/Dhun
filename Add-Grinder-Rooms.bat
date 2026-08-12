@echo off
REM ============================================================================
REM  Add-Grinder-Rooms  -  give Grinder extra voices, so more than one listening
REM  room can play music at the same time.
REM
REM  WHY THIS EXISTS: a Discord bot can hold only ONE voice connection per server.
REM  One Grinder = one room with music and every other room silent - and worse, it
REM  WALKS OUT of a busy room to serve one person next door. Extra bot identities
REM  are free, and each one can hold its own room.
REM
REM  WHAT YOU NEED FIRST, in the Discord Developer Portal:
REM    New Application  ->  name it "Grinder"  ->  Bot  ->  Reset Token  ->  Copy
REM    Then invite it to your server with the same permissions as Grinder, and
REM    make sure it can See and Connect to your listening-rooms category.
REM    Repeat for a third room if you want one.
REM
REM  YOUR TOKEN NEVER LEAVES THIS PC. It is written straight into
REM  services\discord-bot\.env, which git ignores. It is never shown on screen,
REM  never logged, and never sent anywhere.
REM
REM  It EDITS the .env rather than replacing it, so your server id and channel
REM  ids survive - as does Set-Grinder-Token.bat now.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Add Grinder Rooms

if not exist "services\discord-bot\.env" (
  echo.
  echo   No settings file yet. Run Set-Grinder-Token.bat first to set up the main bot.
  echo.
  pause
  exit /b 1
)

echo.
echo   Extra Grinder voices - one per additional listening room
echo   --------------------------------------------------------
echo   In the Discord Developer Portal:
echo     New Application  -^>  Bot  -^>  Reset Token  -^>  Copy
echo     Then invite it to your server, same permissions as Grinder.
echo.
echo   Paste one token per extra room below. Nothing appears on screen as you
echo   paste. Press Enter on an empty line when you are done.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "services\discord-bot\scripts\Set-GrinderSecret.ps1" -Path "services\discord-bot\.env" -Key GRINDER_ROOM_TOKENS -Prompt "Token for Grinder" -Multiple

if errorlevel 1 (
  echo.
  echo   Nothing changed.
  echo.
  pause
  exit /b 1
)

echo.
echo   ====================================================================
echo   Saved. Grinder now has extra voices for extra rooms.
echo   ====================================================================
echo.
echo   Next: close the Grinder window and run Start-Grinder.bat again.
echo   The startup log will say how many rooms can have sound at once.
echo.
pause

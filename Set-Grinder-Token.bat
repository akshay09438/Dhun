@echo off
REM ============================================================================
REM  Set-Grinder-Token  -  double-click this, paste your bot token, press Enter.
REM  It saves the token privately for the Grinder Discord bot.
REM  The token is stored ONLY on this PC (services\discord-bot\.env) and is
REM  never committed to git. Nobody else sees it.
REM
REM  FIXED 2026-08-12: this used to write the .env with a single ">", which
REM  OVERWRITES THE WHOLE FILE. Running it a second time - the obvious thing to
REM  do after resetting a token - silently threw away the server id and all four
REM  channel ids, and the bot came back up half-broken with nothing in the log
REM  saying why. It now replaces one line and leaves the rest alone.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Set Grinder Token

echo.
echo   Grinder ^(Prompt-DJ Discord bot^) - token setup
echo   ---------------------------------------------
echo   1^) In the Discord Developer Portal: your app -^> Bot -^> Reset Token -^> Copy.
echo   2^) Right-click below to paste it, then press Enter.
echo.
echo   Nothing appears on screen as you paste. That is deliberate - a token left
echo   in this window's scrollback is a token that has to be reset.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "services\discord-bot\scripts\Set-GrinderSecret.ps1" -Path "services\discord-bot\.env" -Key DISCORD_TOKEN -Prompt "Paste bot token"

if errorlevel 1 (
  echo.
  echo   Run this again when you have the token ready.
  echo.
  pause
  exit /b 1
)

echo.
echo   Saved to services\discord-bot\.env  ^(private, never committed^).
echo   Next: run Start-Grinder.bat to go live.
echo.
pause

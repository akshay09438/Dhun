@echo off
REM ============================================================================
REM  Add-Grinder-Rooms  -  give Grinder extra voices, so more than one listening
REM  room can play music at the same time.
REM
REM  WHY THIS EXISTS: a Discord bot can hold only ONE voice connection per server.
REM  One Grinder = one room with music and every other room silent. Extra bot
REM  identities are free, and each one can hold its own room.
REM
REM  WHAT YOU NEED FIRST, in the Discord Developer Portal:
REM    New Application  ->  name it "Grinder 2"  ->  Bot  ->  Reset Token  ->  Copy
REM    Then invite it to your server with the same permissions as Grinder.
REM    Repeat for "Grinder 3" if you want a third room.
REM
REM  YOUR TOKEN NEVER LEAVES THIS PC. It is written straight into
REM  services\discord-bot\.env, which git ignores. It is never shown on screen,
REM  never logged, and never sent anywhere.
REM
REM  UNLIKE Set-Grinder-Token.bat, this EDITS the .env instead of overwriting it,
REM  so your server id and channel ids survive.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Add Grinder Rooms

if not exist "services\discord-bot\.env" (
  echo.
  echo   No .env found. Run Set-Grinder-Token.bat first to set up the main bot.
  echo.
  pause
  exit /b 1
)

echo.
echo   Extra Grinder voices - one per additional listening room
echo   --------------------------------------------------------
echo   In the Discord Developer Portal:
echo     New Application  -^>  name it "Grinder 2"  -^>  Bot  -^>  Reset Token  -^>  Copy
echo     Then invite it to your server, same permissions as Grinder.
echo.
echo   Paste the token below. Nothing is shown on screen as you paste.
echo   Press Enter on an empty line to stop adding.
echo.

set "TOKENS="
set /p T1=Token for Grinder 2 ^(Enter to skip^):
if not "%T1%"=="" set "TOKENS=%T1%"

if not "%T1%"=="" (
  set /p T2=Token for Grinder 3 ^(Enter to skip^):
)

setlocal enabledelayedexpansion
if not "!T2!"=="" set "TOKENS=!TOKENS!,!T2!"

if "!TOKENS!"=="" (
  echo.
  echo   Nothing entered - no changes made.
  echo.
  pause
  exit /b 0
)

REM  Edit the .env in place: replace any existing GRINDER_ROOM_TOKENS line and keep
REM  every other setting. PowerShell rather than batch because batch cannot rewrite
REM  one line of a file without mangling the rest.
powershell -NoProfile -Command ^
  "$p='services\discord-bot\.env';" ^
  "$lines=@(Get-Content $p -ErrorAction SilentlyContinue ^| Where-Object { $_ -notmatch '^^GRINDER_ROOM_TOKENS=' });" ^
  "$lines += ('GRINDER_ROOM_TOKENS=' + $env:TOKENS);" ^
  "Set-Content -Path $p -Value $lines -Encoding ascii"

echo.
echo   ====================================================================
echo   Saved. Grinder now has extra voices for extra rooms.
echo   ====================================================================
echo.
echo   Next: close the Grinder window and run Start-Grinder.bat again.
echo.
pause

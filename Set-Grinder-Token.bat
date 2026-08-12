@echo off
REM ============================================================================
REM  Set-Grinder-Token  —  double-click this, paste your bot token, press Enter.
REM  It saves the token privately for the Grinder Discord bot.
REM  The token is stored ONLY on this PC (services\discord-bot\.env) and is
REM  never committed to git. Nobody else sees it.
REM ============================================================================
setlocal
cd /d "%~dp0"

echo.
echo   Grinder ^(Prompt-DJ Discord bot^) — token setup
echo   ---------------------------------------------
echo   1^) In the Discord Developer Portal: your app -^> Bot -^> Reset Token -^> Copy.
echo   2^) Right-click here to paste it, then press Enter.
echo.
set /p TOK=Paste bot token:

if "%TOK%"=="" (
  echo.
  echo   No token entered — nothing was saved. Run this again when ready.
  echo.
  pause
  exit /b 1
)

> "services\discord-bot\.env" echo DISCORD_TOKEN=%TOK%
echo.
echo   Saved to services\discord-bot\.env  ^(private, never committed^).
echo   You're done for tonight. In the morning, run Start-Grinder.bat to go live.
echo.
pause

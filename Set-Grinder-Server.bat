@echo off
REM ============================================================================
REM  Set-Grinder-Server  —  makes the slash commands appear INSTANTLY in your server.
REM  Paste your Discord Server ID, press Enter. (Without this, a brand-new
REM  command can take up to an hour to show up.)
REM
REM  To get your Server ID: Discord -> User Settings -> Advanced -> turn on
REM  Developer Mode. Then right-click your server's icon -> Copy Server ID.
REM ============================================================================
setlocal
cd /d "%~dp0"

if not exist "services\discord-bot\.env" (
  echo.
  echo   No token file yet. Run Set-Grinder-Token.bat first.
  echo.
  pause
  exit /b 1
)

echo.
echo   Paste your Discord SERVER ID, then press Enter:
set /p GID=Server ID:

if "%GID%"=="" (
  echo   Nothing entered — nothing changed.
  pause
  exit /b 1
)

>> "services\discord-bot\.env" echo DISCORD_GUILD_ID=%GID%
echo.
echo   Saved. Now run ^(or restart^) Start-Grinder.bat — /grind will appear instantly.
echo.
pause

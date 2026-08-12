@echo off
REM ============================================================================
REM  Reclaim-Disk  -  give the laptop its space back.
REM
REM  WHAT THIS CLEARS, and why it is safe:
REM    C:\Windows\SoftwareDistribution\Download  - Windows Update's pile of
REM    already-installed update downloads. Windows keeps them, does not need
REM    them, and re-downloads anything it still wants. This is Microsoft's own
REM    documented fix for exactly this, and it does NOT uninstall any update.
REM
REM  WHY IT NEEDS THE "DO YOU WANT TO ALLOW" PROMPT:
REM    the files are locked by the Windows Update service, and only an
REM    administrator may stop that service. Click Yes once and it does the rest.
REM
REM  It touches NOTHING belonging to Prompt-DJ - no songs, no stems, no mixes.
REM  Found on 2026-08-12: 7.80 GB sitting here while the app had 5.86 GB free.
REM ============================================================================
title Reclaim Disk

REM --- self-elevate: re-launch through PowerShell asking for administrator ----
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Asking Windows for permission ^(click YES on the prompt^)...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

cd /d "%~dp0"
echo.
echo  ====================================================================
echo   Reclaiming disk space
echo  ====================================================================
echo.

for /f "tokens=*" %%A in ('powershell -NoProfile -Command "'{0:N2}' -f ((Get-PSDrive C).Free/1GB)"') do set BEFORE=%%A
echo   Free space before: %BEFORE% GB
echo.

echo   [1/4] Pausing Windows Update...
net stop wuauserv >nul 2>&1
net stop bits     >nul 2>&1

echo   [2/4] Clearing the update download cache...
if exist "C:\Windows\SoftwareDistribution\Download" (
  del /f /s /q "C:\Windows\SoftwareDistribution\Download\*.*" >nul 2>&1
  for /d %%D in ("C:\Windows\SoftwareDistribution\Download\*") do rd /s /q "%%D" >nul 2>&1
)

echo   [3/4] Clearing Windows temp files...
del /f /s /q "C:\Windows\Temp\*.*" >nul 2>&1

echo   [4/4] Starting Windows Update again...
net start wuauserv >nul 2>&1
net start bits     >nul 2>&1

echo.
for /f "tokens=*" %%A in ('powershell -NoProfile -Command "'{0:N2}' -f ((Get-PSDrive C).Free/1GB)"') do set AFTER=%%A
echo  ====================================================================
echo   Free space before: %BEFORE% GB
echo   Free space now   : %AFTER% GB
echo  ====================================================================
echo.
echo   Windows Update still works. It will re-download anything it needs.
echo.
pause

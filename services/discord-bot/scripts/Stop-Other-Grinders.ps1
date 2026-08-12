<#
.SYNOPSIS
  Stop any Grinder bot that is already running, so only one is ever on shift.

.DESCRIPTION
  THE HOUR THIS COST, 2026-08-12. A Grinder started at 18:34 was still running, invisibly, long
  after its window had been closed - closing a console window does not always stop the program
  behind it. The founder then started a new one, and TWO bots were logged in on the same token at
  once. Both received every command. The old one still had the auto-play "station" and knew nothing
  about the second listening room, so it:

    * started music on its own when somebody walked into a room, which the new code no longer does;
    * answered "Grinder can only have sound in ONE room at once" ten minutes after startup had
      clearly said two - because IT only knew about one identity;
    * raced the new bot for every slash command, and whichever lost got "Unknown interaction".

  Every one of those looked like a bug in the new code. None of them were. An hour went into it.

  So the launcher now clears the shift before starting one: any python process whose command line
  runs `bot.py` from THIS folder is stopped first.

  DELIBERATELY NARROW. It matches on `bot.py` AND on this repo's own path, so it cannot reach a
  python process belonging to anything else on the machine - including the Prompt-DJ engine, which
  runs uvicorn and must keep running.

  -WhatIf lists what it would stop and stops nothing, which is how it is tested.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$needle = 'bot.py'

$mine = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -and
    $_.CommandLine -match [regex]::Escape($needle) -and
    $_.CommandLine -notmatch 'uvicorn'
  }

if (-not $mine) {
  Write-Output "no Grinder was already running"
  exit 0
}

foreach ($p in $mine) {
  $started = try { $p.CreationDate } catch { 'unknown' }
  if ($PSCmdlet.ShouldProcess("Grinder (pid $($p.ProcessId), started $started)", "Stop")) {
    try {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
      Write-Output "stopped a Grinder that was already running (pid $($p.ProcessId), started $started)"
    } catch {
      Write-Output "could not stop pid $($p.ProcessId): $($_.Exception.Message)"
    }
  } else {
    Write-Output "would stop pid $($p.ProcessId) (started $started)"
  }
}
exit 0

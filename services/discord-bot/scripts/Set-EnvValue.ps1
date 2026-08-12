<#
.SYNOPSIS
  Set one KEY=value in a .env file WITHOUT destroying anything else in it.

.DESCRIPTION
  THE BUG THIS EXISTS TO FIX. Set-Grinder-Token.bat used to write the file with a single `>`:

      > "services\discord-bot\.env" echo DISCORD_TOKEN=%TOK%

  which overwrites the WHOLE file. Running it a second time - the obvious thing to do when a token
  is reset - silently discarded DISCORD_GUILD_ID and all four channel/category ids. The bot would
  then come back up half-broken: no rooms, no status message, no showcase, and nothing in the log
  saying why, because from its point of view those settings simply were not configured.

  This replaces the one line and leaves every other line exactly where it was, comments and blanks
  included. If the key is not there yet it is appended. Later duplicates of the same key are dropped,
  because the bot's own reader honours the FIRST occurrence and a stale second copy would be a
  setting that looks changed and is not.

  It never prints the value. Deliberately non-interactive so it can be tested; the prompting lives in
  Set-GrinderSecret.ps1.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [Parameter(Mandatory = $true)][string]$Key,
  [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
)

$ErrorActionPreference = 'Stop'

$existing = @()
if (Test-Path -LiteralPath $Path) {
  $existing = @(Get-Content -LiteralPath $Path)
}

$pattern = '^\s*' + [regex]::Escape($Key) + '\s*='
$replaced = $false
$out = New-Object System.Collections.Generic.List[string]

foreach ($line in $existing) {
  if ($line -match $pattern) {
    if (-not $replaced) {
      $out.Add("$Key=$Value")     # in place, so the file keeps the shape the founder knows
      $replaced = $true
    }
    # any further copies are dropped on purpose - see the note above
    continue
  }
  $out.Add($line)
}

if (-not $replaced) {
  $out.Add("$Key=$Value")
}

$dir = Split-Path -Parent $Path
if ($dir -and -not (Test-Path -LiteralPath $dir)) {
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Set-Content -LiteralPath $Path -Value $out.ToArray() -Encoding ascii
Write-Output "saved $Key"

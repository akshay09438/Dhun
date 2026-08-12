<#
.SYNOPSIS
  Ask for a bot token (hidden as it is typed) and save it into the .env, keeping everything else.

.DESCRIPTION
  Two jobs the .bat files used to do badly.

  1. THE PROMISE ABOUT SECRECY. Add-Grinder-Rooms.bat said "Nothing is shown on screen as you paste"
     while using `set /p`, which echoes every character. Read-Host -AsSecureString actually hides it,
     so the sentence is now true. It matters: a token in the scrollback of a window that gets
     screen-shared or recorded is a token that has to be reset.

  2. NOT DESTROYING THE REST OF THE FILE - see Set-EnvValue.ps1 for the bug that caused.

  -Multiple gathers one token per extra listening room, stopping at the first blank, and joins them
  with commas, which is the shape GRINDER_ROOM_TOKENS is read in.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [Parameter(Mandatory = $true)][string]$Key,
  [Parameter(Mandatory = $true)][string]$Prompt,
  [switch]$Multiple,
  [int]$StartAt = 2
)

$ErrorActionPreference = 'Stop'

function Read-Secret([string]$label) {
  $secure = Read-Host -Prompt $label -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { return ([Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)).Trim() }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Test-LooksLikeAToken([string]$value) {
  # Not validation of a real token - only a check for the two paste accidents that produce a
  # confusing failure much later: grabbing the APPLICATION ID (a short number) instead of the token,
  # or catching surrounding text. Saying so here beats a bot that simply will not log in.
  if ($value.Length -lt 40) { return "that looks too short for a bot token - did you copy the Application ID by mistake?" }
  if ($value -match '\s') { return "that has a space in it - copy just the token, nothing around it" }
  if ($value -match ',') { return "that has a comma in it, which is the separator between tokens" }
  return $null
}

$existing = @()
if (Test-Path -LiteralPath $Path) { $existing = @(Get-Content -LiteralPath $Path) }
$mainLine = $existing | Where-Object { $_ -match '^\s*DISCORD_TOKEN\s*=' } | Select-Object -First 1
$mainToken = if ($mainLine) { ($mainLine -split '=', 2)[1].Trim() } else { '' }

$collected = New-Object System.Collections.Generic.List[string]
$n = $StartAt

while ($true) {
  $label = if ($Multiple) { "$Prompt $n (press Enter to stop)" } else { $Prompt }
  $value = Read-Secret $label

  if ([string]::IsNullOrWhiteSpace($value)) { break }

  $why = Test-LooksLikeAToken $value
  if ($why) {
    Write-Host ""
    Write-Host "   Not saved - $why" -ForegroundColor Yellow
    Write-Host ""
    if (-not $Multiple) { exit 2 }
    continue
  }

  if ($mainToken -and $value -eq $mainToken) {
    # The one mistake that would look like a WORSE bug than the one being fixed: the same token is
    # the same identity, so Discord would move the single connection and the FIRST room would go
    # silent mid-song the moment the second one started.
    Write-Host ""
    Write-Host "   Not saved - that is the same token as the main Grinder. An extra room needs a" -ForegroundColor Yellow
    Write-Host "   NEW application in the Developer Portal, not the same one pasted twice." -ForegroundColor Yellow
    Write-Host ""
    if (-not $Multiple) { exit 2 }
    continue
  }

  if ($collected -contains $value) {
    Write-Host "   Skipped - you already pasted that one." -ForegroundColor Yellow
    continue
  }

  $collected.Add($value)
  Write-Host "   Got it." -ForegroundColor Green
  if (-not $Multiple) { break }
  $n = $n + 1
}

if ($collected.Count -eq 0) {
  Write-Host ""
  Write-Host "   Nothing entered - no changes were made." -ForegroundColor Yellow
  exit 1
}

$joined = [string]::Join(',', $collected.ToArray())
& (Join-Path $PSScriptRoot 'Set-EnvValue.ps1') -Path $Path -Key $Key -Value $joined | Out-Null

Write-Host ""
if ($Multiple) {
  $rooms = $collected.Count + 1
  Write-Host "   Saved. Grinder can now have sound in $rooms rooms at the same time." -ForegroundColor Green
} else {
  Write-Host "   Saved. Every other setting in the file was left alone." -ForegroundColor Green
}
exit 0

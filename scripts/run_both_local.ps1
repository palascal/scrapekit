# Local runner helper — saxbot only (AudiTT retired).
#
# Exemples:
#   .\run_both_local.ps1
#   .\run_both_local.ps1 -Only saxbot

param(
  [ValidateSet("saxbot")]
  [string]$Only = "saxbot"
)

$ErrorActionPreference = "Stop"
$Documents = Split-Path -Parent $PSScriptRoot
$Shared = Join-Path $PSScriptRoot "run_local_project.ps1"

$jobs = @(
  @{
    Label = "Saxbot"
    AppRoot = Join-Path $Documents "saxbot"
    KvNamespaceId = "3eef1a1ab44e4601b27a6028ae202b2f"
    BrowserProfileEnv = "SAXBOT_BROWSER_PROFILE"
    SkipResidentialEnv = "SAXBOT_SKIP_RESIDENTIAL"
  }
)

foreach ($j in $jobs) {
  if (-not (Test-Path $j.AppRoot)) {
    Write-Host "Skip $($j.Label): introuvable ($($j.AppRoot))"
    continue
  }
  Write-Host ""
  Write-Host "======== $($j.Label) ========"
  & $Shared `
    -AppRoot $j.AppRoot `
    -KvNamespaceId $j.KvNamespaceId `
    -BrowserProfileEnv $j.BrowserProfileEnv `
    -SkipResidentialEnv $j.SkipResidentialEnv `
    -Label $j.Label
}

Write-Host ""
Write-Host "Termine."

# Shared local scrape + Cloudflare KV publish.
# Used by saxbot and AudiTT thin wrappers.
#
# Usage:
#   .\run_local_project.ps1 -AppRoot "C:\...\saxbot" -KvNamespaceId "..." [-BrowserProfileEnv "SAXBOT_BROWSER_PROFILE"]

param(
  [Parameter(Mandatory = $true)][string]$AppRoot,
  [Parameter(Mandatory = $true)][string]$KvNamespaceId,
  [string]$ListingsKey = "listings_v1",
  [string]$BrowserProfileEnv = "",
  [string]$SkipResidentialEnv = "",
  [string]$Label = "scrape"
)

$ErrorActionPreference = "Stop"
$AppRoot = (Resolve-Path $AppRoot).Path
Set-Location $AppRoot

function Import-DotEnv([string]$Path) {
  if (-not (Test-Path $Path)) { return }
  Get-Content $Path -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or ($line -notmatch "=")) { return }
    $i = $line.IndexOf("=")
    $key = $line.Substring(0, $i).Trim()
    $val = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
    if (-not $key) { return }
    Set-Item -Path "Env:$key" -Value $val
  }
}

Import-DotEnv (Join-Path $AppRoot "src\.env.local")

$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

if ($SkipResidentialEnv) {
  Remove-Item "Env:$SkipResidentialEnv" -ErrorAction SilentlyContinue
}

if ($BrowserProfileEnv) {
  $profileDir = Join-Path $AppRoot "data\browser_profile"
  Set-Item -Path "Env:$BrowserProfileEnv" -Value $profileDir
  Write-Host "$Label local scrape (profile=$profileDir)"
} else {
  Write-Host "$Label local scrape"
}

Set-Location (Join-Path $AppRoot "src")
python -u main.py
Set-Location $AppRoot

$Listings = Join-Path $AppRoot "docs\data\listings.json"
if (-not (Test-Path $Listings)) {
  Write-Host "Pas de listings.json — skip publish KV."
  exit 0
}

if (-not $env:CLOUDFLARE_API_TOKEN) {
  Write-Host ""
  Write-Host "Publish KV ignore: CLOUDFLARE_API_TOKEN manquant dans src\.env.local"
  Write-Host "  (evite le login OAuth navigateur qui time-out)."
  Write-Host "Les annonces restent en local dans docs\data\listings.json"
  exit 0
}

if (-not $env:CLOUDFLARE_ACCOUNT_ID) {
  Write-Host "CLOUDFLARE_ACCOUNT_ID manquant — skip publish KV."
  exit 0
}

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
  Write-Host "npx absent — skip publish KV."
  exit 0
}

Write-Host "Publish listings to Cloudflare KV..."
try {
  npx --yes wrangler@3 kv key put --namespace-id=$KvNamespaceId $ListingsKey --path=$Listings
  Write-Host "KV publish OK."
} catch {
  Write-Host "KV publish echec: $_"
  Write-Host "Les annonces restent en local dans docs\data\listings.json"
  exit 0
}

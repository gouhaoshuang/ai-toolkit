<#
.SYNOPSIS
  Deploy agy-skills from this repo to local ~/.gemini/config/plugins/skills
  and optionally sync to a remote Linux host via ssh/scp.

.USAGE
  powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -RemoteHost L40
  powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -RemoteHost L40 -DryRun
#>
[CmdletBinding()]
param(
  [string]$LocalPluginName = "skills",
  [string]$RemoteHost = "",
  [string]$RemotePluginDir = "~/.gemini/config/plugins/skills",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LocalTarget = Join-Path $env:USERPROFILE ".gemini\config\plugins\$LocalPluginName"

$BundleItems = @("plugin.json", "README.md", "LICENSE", "assets", "skills", "sidecars")

Write-Host "[agy-skills] Source: $RepoRoot" -ForegroundColor Cyan
Write-Host "[agy-skills] Local : $LocalTarget" -ForegroundColor Cyan

if (-not $DryRun) {
  New-Item -ItemType Directory -Force -Path $LocalTarget | Out-Null
  foreach ($item in $BundleItems) {
    $src = Join-Path $RepoRoot $item
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $LocalTarget $item
    if (Test-Path $src -PathType Container) {
      New-Item -ItemType Directory -Force -Path $dst | Out-Null
      Copy-Item -Recurse -Force -Path (Join-Path $src "*") -Destination $dst
    } else {
      Copy-Item -Force -Path $src -Destination $dst
    }
  }
  Write-Host "[agy-skills] Updated local plugin at $LocalTarget" -ForegroundColor Green
} else {
  Write-Host "[agy-skills] DryRun: would copy [$($BundleItems -join ', ')] -> $LocalTarget" -ForegroundColor Yellow
}

if ($RemoteHost) {
  Write-Host "[agy-skills] Remote: ${RemoteHost}:${RemotePluginDir}" -ForegroundColor Cyan
  if ($DryRun) {
    Write-Host "[agy-skills] DryRun: would sync [$($BundleItems -join ', ')] -> ${RemoteHost}:${RemotePluginDir}" -ForegroundColor Yellow
    exit 0
  }

  & ssh $RemoteHost "mkdir -p $RemotePluginDir"
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to create remote directory on $RemoteHost (exit code $LASTEXITCODE)"
  }

  $srcPaths = @()
  foreach ($item in $BundleItems) {
    $p = Join-Path $RepoRoot $item
    if (Test-Path $p) { $srcPaths += $p }
  }

  & scp -r @srcPaths "${RemoteHost}:${RemotePluginDir}/"
  if ($LASTEXITCODE -ne 0) {
    throw "scp failed with exit code $LASTEXITCODE"
  }

  Write-Host "[agy-skills] Synced to ${RemoteHost}:${RemotePluginDir} successfully." -ForegroundColor Green
}

#Requires -Version 5.1
<#
.SYNOPSIS
  Vendor a curated subset of the taste-skill repo into .agents/skills.

.DESCRIPTION
  DSH discovers skills by listing the DIRECT children of a skill root and
  looking for SKILL.md (depth 1, non-recursive). This script vendors the
  selected taste-skill folders into .agents/skills/ so they are discovered
  alongside the academic-research-skills already vendored in .dsh/skills/.

  Why a second root instead of .dsh/skills:
    tools/install_ars_skills.ps1 wipes and re-creates .dsh/skills on every
    run. Anything else living there would be destroyed. .agents/skills is
    an equally valid project skill root (rank 200 in the DSH discovery
    table), so the two installers cannot clobber each other.

  Layout produced:
    .agents/skills/<install-name>/SKILL.md   <- discovered as a skill
    .agents/skills/.upstream/                <- provenance; no SKILL.md
    .agents/skills/.taste-install.json       <- install manifest

  Install names come from each SKILL.md frontmatter `name:`, matching
  upstream's own install.sh semantics. Upstream folder names differ from
  install names (skills/redesign-skill -> redesign-existing-projects).

  Curated subset: see $CuratedSkills. Landing-page, image-generation and
  superseded-version skills are skipped; pass -All to install every folder.

  Known limitation: taste-skill's scripts/inspect.mjs drives a real browser
  over the Chrome DevTools Protocol, which the DSH file sandbox blocks on
  this host. scripts/lint.mjs works and needs nothing but Node.

.PARAMETER RepoUrl
  Upstream repository. Defaults to the public GitHub URL.

.PARAMETER Ref
  Optional tag/branch/commit to check out after cloning.

.PARAMETER SourceDir
  Local clone to use. Cloned from RepoUrl when missing.

.PARAMETER Update
  Fetch and hard-reset an existing clone to origin/HEAD before vendoring.

.PARAMETER All
  Install every skill folder found, not just the curated subset.

.PARAMETER KeepGitDir
  Keep the clone's .git directory. Without this the clone becomes a plain
  tree and a later -Update has to re-clone from scratch.

.EXAMPLE
  pwsh -File tools/install_taste_skills.ps1

.EXAMPLE
  pwsh -File tools/install_taste_skills.ps1 -Update

.NOTES
  Keep this file ASCII-only: Windows PowerShell 5.1 parses BOM-less .ps1
  files as the OEM codepage, so non-ASCII bytes corrupt parsing.
#>
[CmdletBinding()]
param(
    [string]$RepoUrl = 'https://github.com/Leonxlnx/taste-skill.git',
    [string]$Ref = '',
    [string]$SourceDir = '',
    [switch]$Update,
    [switch]$All,
    [switch]$KeepGitDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($SourceDir)) { $SourceDir = Join-Path $root '.tmp\taste' }
$destRoot = Join-Path $root '.agents\skills'
$upstreamDir = Join-Path $destRoot '.upstream'

# Relevant to upgrading an existing Vue dashboard. Excluded on purpose:
#   imagegen-frontend-web / -mobile, image-to-code, brandkit -> image generation
#   gpt-taste, stitch-design-taste                           -> landing pages
#   design-taste-frontend-v1 / -v2-experimental              -> superseded copies
$CuratedSkills = @(
    'redesign-skill',
    'soft-skill',
    'minimalist-skill',
    'brutalist-skill',
    'taste-skill',
    'output-skill'
)

$ProvenanceFiles = @(
    'LICENSE', 'README.md', 'CHANGELOG.md', 'install.sh', 'skill.sh',
    '.gitattributes', '.gitignore'
)
$ProvenanceDirs = @('.claude-plugin', '.codex-plugin')

$script:Installed = @()

function Write-Step {
    param([string]$Message)
    Write-Host ''
    Write-Host "== $Message" -ForegroundColor Cyan
}

# This host pins GitHub to localhost and re-signs TLS with a local root CA,
# so every git invocation needs the exported CA. tools/setup_git_trust.ps1
# writes it. Without it git falls back to schannel and fails with
# SEC_E_NO_CREDENTIALS.
$script:GitTrust = @()
function Invoke-Git {
    param([string[]]$GitArgs)
    & git @script:GitTrust @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Get-SkillInstallName {
    param([string]$SkillMd)
    $text = Get-Content -LiteralPath $SkillMd -Raw -Encoding UTF8
    $fm = [regex]::Match($text, '(?s)\A---\r?\n(.*?)\r?\n---')
    if (-not $fm.Success) { return $null }
    $name = [regex]::Match($fm.Groups[1].Value, '(?m)^name:\s*(\S+)\s*$')
    if (-not $name.Success) { return $null }
    return $name.Groups[1].Value
}

Write-Host ''
Write-Host '=== taste-skill installer ===' -ForegroundColor Cyan
Write-Host "repo       : $RepoUrl"
Write-Host "source     : $SourceDir"
Write-Host "destination: $destRoot"

# --- 1. obtain the source tree ---------------------------------------------
Write-Step 'Obtaining source tree'

$caFile = Join-Path $root '.git-trust\tool-root-ca.pem'
if (Test-Path $caFile) {
    $script:GitTrust = @(
        '-c', 'http.sslBackend=openssl',
        '-c', "http.sslCAInfo=$caFile"
    )
    Write-Host "  TLS: using $caFile"
} else {
    Write-Host '  TLS: no .git-trust\tool-root-ca.pem -- run tools/setup_git_trust.ps1 if git fails' -ForegroundColor Yellow
}

if (-not (Test-Path $SourceDir)) {
    Write-Host "  cloning (shallow) into $SourceDir"
    Invoke-Git -GitArgs @('clone', '--depth', '1', $RepoUrl, $SourceDir)
} elseif ($Update) {
    if (-not (Test-Path (Join-Path $SourceDir '.git'))) {
        Write-Host '  -Update requested but the clone has no .git (a previous run removed it)' -ForegroundColor Yellow
        Write-Host '  deleting the tree and re-cloning'
        Remove-Item -LiteralPath $SourceDir -Recurse -Force
        Invoke-Git -GitArgs @('clone', '--depth', '1', $RepoUrl, $SourceDir)
    } else {
        Write-Host '  -Update: fetching and hard-resetting the existing clone'
        Invoke-Git -GitArgs @('-C', $SourceDir, 'fetch', '--depth', '1', 'origin')
        Invoke-Git -GitArgs @('-C', $SourceDir, 'reset', '--hard', 'FETCH_HEAD')
    }
} else {
    Write-Host '  reusing existing clone (pass -Update to refresh it)'
}

if (-not [string]::IsNullOrWhiteSpace($Ref)) {
    Write-Host "  checking out $Ref"
    Invoke-Git -GitArgs @('-C', $SourceDir, 'checkout', '--force', $Ref)
}

$skillsDir = Join-Path $SourceDir 'skills'
if (-not (Test-Path $skillsDir)) {
    throw "no skills/ directory in $SourceDir -- is this the taste-skill repo?"
}

$commit = (& git -C $SourceDir rev-parse HEAD).Trim()
$commitDate = (& git -C $SourceDir log -1 --format=%cI).Trim()
Write-Host "  commit: $commit"

# --- 2. pick the skill folders ---------------------------------------------
Write-Step 'Selecting skill folders'

if ($All) {
    $sources = @(Get-ChildItem -LiteralPath $skillsDir -Directory -Force | ForEach-Object { $_.Name })
    Write-Host "  -All: $($sources.Count) folders"
} else {
    $sources = $CuratedSkills
    Write-Host "  curated subset: $($sources.Count) folders"
}

# --- 3. rebuild the destination --------------------------------------------
Write-Step 'Rebuilding .agents/skills'

if (Test-Path $destRoot) { Remove-Item -LiteralPath $destRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $destRoot | Out-Null

foreach ($srcName in $sources) {
    $srcPath = Join-Path $skillsDir $srcName
    if (-not (Test-Path $srcPath)) { throw "skill folder missing: $srcPath" }
    $skillMd = Join-Path $srcPath 'SKILL.md'
    if (-not (Test-Path $skillMd)) { throw "no SKILL.md in $srcPath" }

    $installName = Get-SkillInstallName -SkillMd $skillMd
    if ([string]::IsNullOrWhiteSpace($installName)) {
        throw "no frontmatter name: in $skillMd"
    }

    Copy-Item -LiteralPath $srcPath -Destination (Join-Path $destRoot $installName) -Recurse -Force
    $script:Installed += $installName
    Write-Host "  $srcName -> $installName"
}

# --- 4. provenance ----------------------------------------------------------
# A .md file sitting directly in the skill root would be discovered as a
# bogus flat skill, so everything that is not a skill goes into .upstream/.
# Copy rather than move: the source clone must stay intact so re-running
# this script (or -Update) still finds the provenance files.
Write-Step 'Copying provenance into .upstream'

New-Item -ItemType Directory -Force -Path $upstreamDir | Out-Null

foreach ($name in $ProvenanceFiles) {
    $src = Join-Path $SourceDir $name
    if (Test-Path $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $upstreamDir $name) -Force
        Write-Host "  $name"
    }
}
foreach ($name in $ProvenanceDirs) {
    $src = Join-Path $SourceDir $name
    if (Test-Path $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $upstreamDir $name) -Recurse -Force
        Write-Host "  $name/"
    }
}

# Sweep anything else that landed at the skill root. Only *.md is dangerous
# for discovery, but a clean root keeps the tree readable.
$stray = @(Get-ChildItem -LiteralPath $destRoot -File -Force)
foreach ($f in $stray) {
    Move-Item -LiteralPath $f.FullName -Destination (Join-Path $upstreamDir $f.Name) -Force
    Write-Host "  swept $($f.Name)"
}

# A nested .git would make the vendored tree look like a submodule.
$nestedGit = Join-Path $destRoot '.git'
if (Test-Path $nestedGit) {
    Remove-Item -LiteralPath $nestedGit -Recurse -Force
    Write-Host '  removed nested .git'
}

if (-not $KeepGitDir) {
    $cloneGit = Join-Path $SourceDir '.git'
    if (Test-Path $cloneGit) {
        Remove-Item -LiteralPath $cloneGit -Recurse -Force
        Write-Host '  removed clone .git'
    }
}

# --- 5. manifest ------------------------------------------------------------
Write-Step 'Writing install manifest'

$manifest = [ordered]@{
    repository  = $RepoUrl
    commit      = $commit
    commitDate  = $commitDate
    installed   = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
    license     = 'MIT (see .upstream/LICENSE)'
    all         = [bool]$All
    skills      = $script:Installed
}
$manifestPath = Join-Path $destRoot '.taste-install.json'
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Host "  $manifestPath"

# --- 6. verify --------------------------------------------------------------
Write-Step 'Verifying'

$failures = @()

foreach ($name in $script:Installed) {
    $skillMd = Join-Path $destRoot "$name\SKILL.md"
    if (-not (Test-Path $skillMd)) { $failures += "missing $name\SKILL.md" }
}

$strayMd = @(Get-ChildItem -LiteralPath $destRoot -File -Force |
    Where-Object { $_.Extension -eq '.md' })
if ($strayMd.Count -gt 0) {
    $failures += "stray .md at skill root: $(($strayMd | ForEach-Object { $_.Name }) -join ', ')"
}

if (Test-Path (Join-Path $destRoot '.git')) { $failures += 'nested .git still present' }

# taste-skill is the only one that ships data + tooling; check a sample.
$tasteProbes = @(
    'design-taste-frontend\library\sites.json',
    'design-taste-frontend\assets\base.css',
    'design-taste-frontend\scripts\lint.mjs',
    'design-taste-frontend\references\colour.md'
)
if ($script:Installed -contains 'design-taste-frontend') {
    foreach ($rel in $tasteProbes) {
        if (-not (Test-Path (Join-Path $destRoot $rel))) { $failures += "missing $rel" }
    }
}

$files = @(Get-ChildItem -LiteralPath $destRoot -Recurse -File -Force)
$sizeMb = [Math]::Round((($files | Measure-Object -Property Length -Sum).Sum / 1MB), 2)

if ($failures.Count -gt 0) {
    Write-Host ''
    Write-Host 'FAILED:' -ForegroundColor Red
    foreach ($f in $failures) { Write-Host "  - $f" -ForegroundColor Red }
    exit 1
}

Write-Host ''
Write-Host "installed skills : $($script:Installed.Count)" -ForegroundColor Green
foreach ($name in $script:Installed) { Write-Host "  $name" -ForegroundColor Green }
Write-Host "files            : $($files.Count)"
Write-Host "size             : $sizeMb MB"
Write-Host ''
Write-Host 'TASTE SKILLS INSTALLED' -ForegroundColor Green
exit 0

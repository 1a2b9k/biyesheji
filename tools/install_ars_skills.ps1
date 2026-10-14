#Requires -Version 5.1
<#
.SYNOPSIS
  Vendor academic-research-skills (ARS) into .dsh/skills so DSH discovers them.

.DESCRIPTION
  DSH discovers skills by listing the DIRECT children of a skill root and
  looking for a SKILL.md inside each child directory (discovery is
  non-recursive). This script vendors the ARS repository into .dsh/skills/
  so that

    1. the five ARS skills are discovered, and
    2. their cross-directory references resolve on disk.

  ARS skill documents link to files OUTSIDE their own skill directory using
  ../shared/..., ../../scripts/... and ../../docs/.... Those links only
  resolve if the vendored tree keeps the UPSTREAM layout, i.e. the ARS
  repository root must BE .dsh/skills/. That is the layout produced here:

    .dsh/skills/academic-paper/            <- skill (has SKILL.md)
    .dsh/skills/academic-paper-reviewer/   <- skill (has SKILL.md)
    .dsh/skills/academic-pipeline/         <- skill (has SKILL.md)
    .dsh/skills/deep-research/             <- skill (has SKILL.md)
    .dsh/skills/sr-screener/               <- skill (has SKILL.md)
    .dsh/skills/shared/                    <- support; no SKILL.md -> not a skill
    .dsh/skills/scripts/                   <- support; no SKILL.md -> not a skill
    .dsh/skills/docs/                      <- support; no SKILL.md -> not a skill
    .dsh/skills/.upstream/                 <- LICENSE / NOTICE / README / metadata

  Directories without a top-level SKILL.md are skipped by discovery, so the
  support directories do not pollute the skill catalog. Root-level .md files
  WOULD be mistaken for flat skills, so all provenance files are moved into
  .upstream/ instead of sitting at the root.

.PARAMETER Ref
  Git ref (tag/branch/sha) to check out. Empty = the clone's default HEAD.

.PARAMETER SourceDir
  Where to clone ARS. Defaults to .tmp/ars (gitignored scratch space).
  An existing clone there is reused and fetched instead of re-cloned.

.PARAMETER KeepGitDir
  Keep the .git directory of the ARS clone. Off by default: the vendored
  payload must not contain a nested repository.

.EXAMPLE
  pwsh -File tools/install_ars_skills.ps1
  pwsh -File tools/install_ars_skills.ps1 -Ref v3.23.0

.NOTES
  Keep this file ASCII-only. Windows PowerShell 5.1 reads a .ps1 as the OEM
  codepage (GBK on this machine) unless the file carries a UTF-8 BOM, which
  turns non-ASCII text into mojibake and breaks parsing.
#>
[CmdletBinding()]
param(
    [string]$RepoUrl = 'https://github.com/Imbad0202/academic-research-skills.git',
    [string]$Ref = '',
    [string]$SourceDir = '',
    [switch]$KeepGitDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- helpers ---
function Get-WorkspaceRoot {
    # tools/ lives directly under the workspace root.
    $here = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $here '..')).Path
}

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Invoke-Git {
    # Wrapper so a non-zero git exit aborts the script instead of being ignored.
    param([string[]]$GitArgs)
    & git @script:GitTrust @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

# ------------------------------------------------------- top-level payload ---
# Copied verbatim from the ARS repository root. Everything a skill references
# at runtime, plus the provenance needed to satisfy the CC-BY-NC-4.0 licence.
$PayloadDirs = @(
    'academic-paper',
    'academic-paper-reviewer',
    'academic-pipeline',
    'deep-research',
    'sr-screener',
    'shared',
    'scripts',
    'docs',
    'agents',
    'commands',
    'hooks',
    'tools',
    'pi',
    '.claude',
    '.claude-plugin'
)

# Provenance / metadata files that live at the ARS repo root. They are moved
# into .upstream/ because a .md file sitting directly in .dsh/skills/ would be
# parsed as a flat skill.
$ProvenanceFiles = @(
    'LICENSE',
    'NOTICE.md',
    'THIRD_PARTY.md',
    'CITATION.cff',
    'README.md',
    'CHANGELOG.md',
    'GOVERNANCE.md',
    'CONTRIBUTING.md',
    'SECURITY.md',
    'POSITIONING.md',
    'QUICKSTART.md',
    'MODE_REGISTRY.md',
    'package.json',
    'pyproject.toml',
    'requirements-dev.txt',
    'requirements-pdf-content-classifier.txt',
    '.gitattributes',
    '.command-invariants.toml'
)

# Development trees that no skill document references and no skill script
# needs. Excluding them keeps the vendored payload ~16 MB instead of ~38 MB.
# NOTE: these are excluded by FULL PATH, never by bare directory name, because
# the skills themselves legitimately contain examples/ and tests/ subdirs.
$ExcludedSubPaths = @(
    'evals',
    'audits',
    'tests',
    'examples',
    '.github',
    'plugin-evals',
    'plugin-evals-citation-check',
    'plugin-evals-citation-locale',
    'scripts\legacy'
)

$SkillNames = @(
    'academic-paper',
    'academic-paper-reviewer',
    'academic-pipeline',
    'deep-research',
    'sr-screener'
)

# -------------------------------------------------------------------- main ---
$root = Get-WorkspaceRoot
if ([string]::IsNullOrWhiteSpace($SourceDir)) {
    $SourceDir = Join-Path $root '.tmp\ars'
}
$destRoot = Join-Path $root '.dsh\skills'

# TLS trust flags for the git child process. This machine's GitHub traffic is
# intercepted and re-signed by the local accelerator, so git must be pointed at
# the exported root CA (see tools/setup_git_trust.ps1). The main repository
# carries these as repo-local config; a fresh clone has no such config yet, so
# they are passed explicitly on every git invocation here.
$script:GitTrust = @()
$caFile = Join-Path $root '.git-trust\tool-root-ca.pem'
if (Test-Path $caFile) {
    $script:GitTrust = @(
        '-c', 'http.sslBackend=openssl',
        '-c', "http.sslCAInfo=$caFile"
    )
} else {
    Write-Host 'WARNING: .git-trust/tool-root-ca.pem is missing.' -ForegroundColor Yellow
    Write-Host '         Run tools/setup_git_trust.ps1 first, or the clone may fail' -ForegroundColor Yellow
    Write-Host '         with "schannel: AcquireCredentialsHandle failed".' -ForegroundColor Yellow
}

Write-Step 'ARS skill installer'
Write-Host "workspace   : $root"
Write-Host "source      : $SourceDir"
Write-Host "destination : $destRoot"
if ($Ref) { Write-Host "ref         : $Ref" }

# 1. obtain the source tree -------------------------------------------------
if (Test-Path (Join-Path $SourceDir '.git')) {
    Write-Step 'Fetching existing ARS clone'
    Invoke-Git -GitArgs @('-C', $SourceDir, 'fetch', '--all', '--tags', '--prune')
    if ($Ref) {
        Invoke-Git -GitArgs @('-C', $SourceDir, 'checkout', $Ref)
    }
} else {
    Write-Step 'Cloning ARS'
    if (Test-Path $SourceDir) { Remove-Item $SourceDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SourceDir) | Out-Null
    Invoke-Git -GitArgs @('clone', '--quiet', $RepoUrl, $SourceDir)
    if ($Ref) {
        Invoke-Git -GitArgs @('-C', $SourceDir, 'checkout', $Ref)
    }
}

$head = (& git -C $SourceDir rev-parse HEAD).Trim()
$headDate = (& git -C $SourceDir log -1 --format=%cI).Trim()
Write-Host "ARS HEAD    : $head ($headDate)"

# 2. wipe the previous install ---------------------------------------------
Write-Step 'Replacing .dsh/skills'
if (Test-Path $destRoot) {
    Remove-Item $destRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $destRoot | Out-Null

# 3. copy the payload -------------------------------------------------------
foreach ($dir in $PayloadDirs) {
    $src = Join-Path $SourceDir $dir
    if (-not (Test-Path $src)) {
        Write-Host "  skip (absent upstream): $dir" -ForegroundColor DarkGray
        continue
    }
    Copy-Item -LiteralPath $src -Destination (Join-Path $destRoot $dir) -Recurse -Force
    Write-Host "  + $dir"
}

# 4. prune development trees (by full path, never by bare name) -------------
Write-Step 'Pruning development trees'
foreach ($rel in $ExcludedSubPaths) {
    $target = Join-Path $destRoot $rel
    if (Test-Path $target) {
        Remove-Item $target -Recurse -Force
        Write-Host "  - $rel"
    }
}

# 5. relocate provenance files into .upstream/ ------------------------------
Write-Step 'Relocating provenance files'
$upstream = Join-Path $destRoot '.upstream'
New-Item -ItemType Directory -Force -Path $upstream | Out-Null
foreach ($name in $ProvenanceFiles) {
    $src = Join-Path $SourceDir $name
    if (Test-Path $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $upstream $name) -Force
    }
}
Write-Host "  -> .upstream/"

# Guard: nothing may sit at the skill-root top level except directories and
# the marker file. A stray .md there would be parsed as a flat skill.
$stray = Get-ChildItem -LiteralPath $destRoot -File -Force |
    Where-Object { $_.Name -ne '.ars-install.json' }
if ($stray) {
    foreach ($f in $stray) {
        Move-Item -LiteralPath $f.FullName -Destination (Join-Path $upstream $f.Name) -Force
        Write-Host "  moved stray file -> .upstream/: $($f.Name)" -ForegroundColor Yellow
    }
}

# 6. drop the nested repository --------------------------------------------
if (-not $KeepGitDir) {
    $nestedGit = Join-Path $destRoot '.git'
    if (Test-Path $nestedGit) { Remove-Item $nestedGit -Recurse -Force }
}

# 7. record install provenance ---------------------------------------------
$manifest = [ordered]@{
    repository = $RepoUrl
    commit     = $head
    commitDate = $headDate
    installed  = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
    license    = 'CC-BY-NC-4.0 (see .upstream/LICENSE)'
    skills     = $SkillNames
}
$manifest | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath (Join-Path $destRoot '.ars-install.json') -Encoding UTF8
Write-Host ''
Write-Host "  wrote .dsh/skills/.ars-install.json"

# 8. verify ----------------------------------------------------------------
Write-Step 'Verifying'
$failed = @()
foreach ($name in $SkillNames) {
    $skillMd = Join-Path $destRoot "$name\SKILL.md"
    if (Test-Path $skillMd) {
        Write-Host "  OK   $name" -ForegroundColor Green
    } else {
        Write-Host "  FAIL $name (no SKILL.md)" -ForegroundColor Red
        $failed += $name
    }
}

# Cross-directory references that the skill documents rely on.
$refTargets = @(
    'shared\output_language_pair.md',
    'shared\references\word_count_conventions.md',
    'scripts\check_acronyms.py',
    'docs\PERFORMANCE.md',
    'docs\RISK_REGISTER.md'
)
foreach ($rel in $refTargets) {
    if (Test-Path (Join-Path $destRoot $rel)) {
        Write-Host "  OK   $rel" -ForegroundColor Green
    } else {
        Write-Host "  FAIL $rel" -ForegroundColor Red
        $failed += $rel
    }
}

$stats = Get-ChildItem -LiteralPath $destRoot -Recurse -File -Force -ErrorAction SilentlyContinue
$mb = [math]::Round((($stats | Measure-Object Length -Sum).Sum) / 1MB, 2)
Write-Host ''
Write-Host "  files=$($stats.Count)  size=$mb MB"

if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host "INSTALL FAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host 'ARS SKILLS INSTALLED' -ForegroundColor Green
Write-Host ''
Write-Host 'NOTE: ARS script invocations in the skill documents are written for a'
Write-Host 'working directory of the ARS repository root, which is now:'
Write-Host "  $destRoot"
Write-Host 'Run them as:  cd .dsh/skills ; python scripts/<name>.py ...'
exit 0

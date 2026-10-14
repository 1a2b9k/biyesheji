#Requires -Version 5.1
<#
.SYNOPSIS
  Verify the vendored academic-research-skills (ARS) installation.

.DESCRIPTION
  Checks the invariants that make the vendored tree actually usable by DSH:

    1. every expected skill has a SKILL.md
    2. no stray .md file sits at the skill-root top level (it would be
       discovered as a bogus "flat skill")
    3. no nested .git directory (would be treated as a submodule)
    4. the cross-directory references the skill documents rely on resolve
    5. no vendored file is swallowed by the project .gitignore
    6. every SKILL.md has valid YAML frontmatter with name + description
    7. the install manifest is present and consistent

  Exits non-zero if any check fails.

.NOTES
  Keep this file ASCII-only (Windows PowerShell 5.1 parses BOM-less .ps1
  files as the OEM codepage).
#>
[CmdletBinding()]
param(
    [string]$Root = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}
$skillRoot = Join-Path $Root '.dsh\skills'

$script:Pass = 0
$script:Fail = 0
$script:Failures = @()

function Test-That {
    param(
        [string]$Name,
        [bool]$Condition,
        [string]$Detail = ''
    )
    if ($Condition) {
        $script:Pass++
        Write-Host "  PASS  $Name" -ForegroundColor Green
    } else {
        $script:Fail++
        $msg = if ($Detail) { "$Name -- $Detail" } else { $Name }
        $script:Failures += $msg
        Write-Host "  FAIL  $msg" -ForegroundColor Red
    }
}

Write-Host ''
Write-Host '=== ARS install verification ===' -ForegroundColor Cyan
Write-Host "skill root : $skillRoot"
Write-Host ''

if (-not (Test-Path $skillRoot)) {
    Write-Host "FAILED: $skillRoot does not exist. Run tools/install_ars_skills.ps1 first." -ForegroundColor Red
    exit 1
}

# --- 1. skills present ------------------------------------------------------
Write-Host '-- skill discovery --' -ForegroundColor Cyan
$expectedSkills = @(
    'academic-paper',
    'academic-paper-reviewer',
    'academic-pipeline',
    'deep-research',
    'sr-screener'
)
foreach ($name in $expectedSkills) {
    $skillMd = Join-Path $skillRoot "$name\SKILL.md"
    Test-That "$name/SKILL.md exists" (Test-Path $skillMd) $skillMd
}

# Discovery is non-recursive, so a stray .md at the top level would be parsed
# as a flat skill named after the file.
$stray = @(Get-ChildItem -LiteralPath $skillRoot -File -Force |
    Where-Object { $_.Extension -eq '.md' })
Test-That 'no stray .md at skill root' ($stray.Count -eq 0) `
    ("found: " + (($stray | ForEach-Object { $_.Name }) -join ', '))

# --- 2. no nested repository ------------------------------------------------
Write-Host ''
Write-Host '-- vendored tree hygiene --' -ForegroundColor Cyan
Test-That 'no nested .git directory' (-not (Test-Path (Join-Path $skillRoot '.git')))

# --- 3. cross-directory references -----------------------------------------
# These are the paths skill documents link to with ../ and ../../. If the
# vendored layout ever stops mirroring the upstream repo root, these break.
Write-Host ''
Write-Host '-- cross-directory references --' -ForegroundColor Cyan
$refTargets = @(
    'shared\output_language_pair.md',
    'shared\handoff_schemas.md',
    'shared\references\word_count_conventions.md',
    'shared\contracts\passport\literature_corpus_entry.schema.json',
    'scripts\check_acronyms.py',
    'scripts\check_pipeline_integrity.py',
    'scripts\ars_anchorize_draft.py',
    'docs\PERFORMANCE.md',
    'docs\RISK_REGISTER.md'
)
foreach ($rel in $refTargets) {
    $full = Join-Path $skillRoot $rel
    Test-That "ref resolves: $rel" (Test-Path $full) $full
}

# --- 4. .gitignore does not swallow vendored files --------------------------
Write-Host ''
Write-Host '-- gitignore coverage --' -ForegroundColor Cyan
$allFiles = @(Get-ChildItem -LiteralPath $skillRoot -Recurse -File -Force -ErrorAction SilentlyContinue)
Test-That 'vendored tree is non-empty' ($allFiles.Count -gt 0) "count=$($allFiles.Count)"

$ignored = @()
foreach ($f in $allFiles) {
    & git -C $Root check-ignore -q -- $f.FullName 2>$null
    if ($LASTEXITCODE -eq 0) { $ignored += $f.FullName }
}
Test-That 'no vendored file is gitignored' ($ignored.Count -eq 0) `
    ("$($ignored.Count) ignored, e.g. " + (($ignored | Select-Object -First 3) -join '; '))

# --- 5. SKILL.md frontmatter ------------------------------------------------
Write-Host ''
Write-Host '-- SKILL.md frontmatter --' -ForegroundColor Cyan
foreach ($name in $expectedSkills) {
    $skillMd = Join-Path $skillRoot "$name\SKILL.md"
    if (-not (Test-Path $skillMd)) { continue }
    $text = Get-Content -LiteralPath $skillMd -Raw -Encoding UTF8

    $hasFence = $text.StartsWith('---')
    Test-That "$name has frontmatter fence" $hasFence

    $fmMatch = [regex]::Match($text, '(?s)\A---\r?\n(.*?)\r?\n---')
    Test-That "$name frontmatter parses" $fmMatch.Success
    if (-not $fmMatch.Success) { continue }

    $fm = $fmMatch.Groups[1].Value
    $nameMatch = [regex]::Match($fm, '(?m)^name:\s*(\S+)\s*$')
    Test-That "$name declares a name" $nameMatch.Success
    if ($nameMatch.Success) {
        Test-That "$name frontmatter name matches directory" ($nameMatch.Groups[1].Value -eq $name) `
            "declared=$($nameMatch.Groups[1].Value) dir=$name"
    }
    Test-That "$name declares a description" ([regex]::IsMatch($fm, '(?m)^description:\s*\S'))
}

# --- 6. install manifest ----------------------------------------------------
Write-Host ''
Write-Host '-- install manifest --' -ForegroundColor Cyan
$manifestPath = Join-Path $skillRoot '.ars-install.json'
Test-That '.ars-install.json exists' (Test-Path $manifestPath) $manifestPath
if (Test-Path $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Test-That 'manifest records a commit' (-not [string]::IsNullOrWhiteSpace($manifest.commit)) `
        "commit=$($manifest.commit)"
    Test-That 'manifest commit is a full sha' ($manifest.commit -match '^[0-9a-f]{40}$') `
        "commit=$($manifest.commit)"
    $manifestSkills = @($manifest.skills)
    Test-That 'manifest lists all skills' ($manifestSkills.Count -eq $expectedSkills.Count) `
        "listed=$($manifestSkills -join ',')"
    Test-That 'manifest license recorded' (-not [string]::IsNullOrWhiteSpace($manifest.license)) `
        "license=$($manifest.license)"
}

# --- summary ----------------------------------------------------------------
Write-Host ''
Write-Host "=== $script:Pass passed, $script:Fail failed ===" -ForegroundColor Cyan
if ($script:Fail -gt 0) {
    Write-Host ''
    Write-Host 'FAILURES:' -ForegroundColor Red
    foreach ($f in $script:Failures) { Write-Host "  - $f" -ForegroundColor Red }
    exit 1
}
Write-Host 'ARS INSTALL VERIFIED' -ForegroundColor Green
exit 0

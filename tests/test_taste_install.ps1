#Requires -Version 5.1
<#
.SYNOPSIS
  Verify the vendored taste-skill installation under .agents/skills.

.DESCRIPTION
  Checks the invariants that make the vendored tree actually usable by DSH:

    1. every expected skill has a SKILL.md
    2. the install directory is named after the frontmatter name, not the
       upstream folder name
    3. no stray .md file sits at the skill-root top level (it would be
       discovered as a bogus "flat skill")
    4. no nested .git directory (would be treated as a submodule)
    5. design-taste-frontend keeps the data files its SKILL.md tells the
       model to read
    6. no vendored file is swallowed by the project .gitignore
    7. every SKILL.md has valid YAML frontmatter with name + description
    8. the install manifest is present and consistent

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
$skillRoot = Join-Path $Root '.agents\skills'

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
Write-Host '=== taste-skill install verification ===' -ForegroundColor Cyan
Write-Host "skill root : $skillRoot"
Write-Host ''

if (-not (Test-Path $skillRoot)) {
    Write-Host "FAILED: $skillRoot does not exist. Run tools/install_taste_skills.ps1 first." -ForegroundColor Red
    exit 1
}

# Upstream folder name -> frontmatter install name. The install directory
# must use the install name: that is the identity DSH shows and the value
# the skill's own documentation refers to.
$expectedSkills = [ordered]@{
    'redesign-skill'   = 'redesign-existing-projects'
    'soft-skill'       = 'high-end-visual-design'
    'minimalist-skill' = 'minimalist-ui'
    'brutalist-skill'  = 'industrial-brutalist-ui'
    'taste-skill'      = 'design-taste-frontend'
    'output-skill'     = 'full-output-enforcement'
}

# --- 1. skills present ------------------------------------------------------
Write-Host '-- skill discovery --' -ForegroundColor Cyan
foreach ($installName in $expectedSkills.Values) {
    $skillMd = Join-Path $skillRoot "$installName\SKILL.md"
    Test-That "$installName/SKILL.md exists" (Test-Path $skillMd) $skillMd
}

# Discovery is non-recursive, so a stray .md at the top level would be parsed
# as a flat skill named after the file.
$stray = @(Get-ChildItem -LiteralPath $skillRoot -File -Force |
    Where-Object { $_.Extension -eq '.md' })
Test-That 'no stray .md at skill root' ($stray.Count -eq 0) `
    ("found: " + (($stray | ForEach-Object { $_.Name }) -join ', '))

# The upstream folder name must NOT be used as the install directory; if it
# were, the skill would still load but under a name its own docs never use.
foreach ($folderName in $expectedSkills.Keys) {
    if ($expectedSkills[$folderName] -eq $folderName) { continue }
    $wrong = Join-Path $skillRoot $folderName
    Test-That "upstream folder name '$folderName' not used as install dir" (-not (Test-Path $wrong)) $wrong
}

# --- 2. tree hygiene --------------------------------------------------------
Write-Host ''
Write-Host '-- vendored tree hygiene --' -ForegroundColor Cyan
Test-That 'no nested .git directory' (-not (Test-Path (Join-Path $skillRoot '.git')))
Test-That '.upstream/ exists' (Test-Path (Join-Path $skillRoot '.upstream'))
Test-That '.upstream/LICENSE exists' (Test-Path (Join-Path $skillRoot '.upstream\LICENSE'))

# --- 3. design-taste-frontend payload ---------------------------------------
# Its SKILL.md tells the model to read these; without them the skill is a
# stub. They are also the bulk of the vendored bytes.
Write-Host ''
Write-Host '-- design-taste-frontend payload --' -ForegroundColor Cyan
$tasteFiles = @(
    'assets\base.css',
    'assets\base.js',
    'library\directions.json',
    'library\heroes.json',
    'library\motions.json',
    'library\palettes.json',
    'library\photos.json',
    'library\sections.json',
    'library\sites.json',
    'library\type.json',
    'references\colour.md',
    'references\copy.md',
    'references\critique.md',
    'references\imagery.md',
    'references\layout.md',
    'references\motion.md',
    'references\research.md',
    'references\tells.md',
    'references\type.md',
    'scripts\assets.mjs',
    'scripts\draw.mjs',
    'scripts\inspect.mjs',
    'scripts\lint.mjs',
    'scripts\lib\cdp.mjs',
    'scripts\lib\probe.mjs',
    'scripts\lib\rules.mjs'
)
foreach ($rel in $tasteFiles) {
    $full = Join-Path $skillRoot "design-taste-frontend\$rel"
    Test-That "payload: $rel" (Test-Path $full) $full
}

# The library files are what make the skill more than a prompt. A truncated
# copy would still pass an existence check, so check they parse as JSON.
foreach ($lib in @('directions', 'palettes', 'sites', 'type')) {
    $p = Join-Path $skillRoot "design-taste-frontend\library\$lib.json"
    if (-not (Test-Path $p)) { continue }
    $ok = $true
    try { $null = Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { $ok = $false }
    Test-That "library/$lib.json parses" $ok $p
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
foreach ($installName in $expectedSkills.Values) {
    $skillMd = Join-Path $skillRoot "$installName\SKILL.md"
    if (-not (Test-Path $skillMd)) { continue }
    $text = Get-Content -LiteralPath $skillMd -Raw -Encoding UTF8

    Test-That "$installName has frontmatter fence" $text.StartsWith('---')

    $fmMatch = [regex]::Match($text, '(?s)\A---\r?\n(.*?)\r?\n---')
    Test-That "$installName frontmatter parses" $fmMatch.Success
    if (-not $fmMatch.Success) { continue }

    $fm = $fmMatch.Groups[1].Value
    $nameMatch = [regex]::Match($fm, '(?m)^name:\s*(\S+)\s*$')
    Test-That "$installName declares a name" $nameMatch.Success
    if ($nameMatch.Success) {
        Test-That "$installName frontmatter name matches directory" ($nameMatch.Groups[1].Value -eq $installName) `
            "declared=$($nameMatch.Groups[1].Value) dir=$installName"
    }
    Test-That "$installName declares a description" ([regex]::IsMatch($fm, '(?m)^description:\s*\S'))
}

# --- 6. install manifest ----------------------------------------------------
Write-Host ''
Write-Host '-- install manifest --' -ForegroundColor Cyan
$manifestPath = Join-Path $skillRoot '.taste-install.json'
Test-That '.taste-install.json exists' (Test-Path $manifestPath) $manifestPath
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

# --- 7. the two skill roots stay independent --------------------------------
# tools/install_ars_skills.ps1 wipes and re-creates .dsh/skills wholesale.
# The taste skills live in .agents/skills precisely so that cannot destroy
# them; assert both roots exist side by side.
Write-Host ''
Write-Host '-- coexistence with .dsh/skills --' -ForegroundColor Cyan
$arsRoot = Join-Path $Root '.dsh\skills'
if (Test-Path $arsRoot) {
    Test-That '.dsh/skills still has academic-paper' (Test-Path (Join-Path $arsRoot 'academic-paper\SKILL.md'))
    Test-That '.dsh/skills does not contain taste skills' `
        (-not (Test-Path (Join-Path $arsRoot 'design-taste-frontend')))
} else {
    Write-Host '  SKIP  .dsh/skills absent (ARS not installed)' -ForegroundColor Yellow
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
Write-Host 'TASTE SKILL INSTALL VERIFIED' -ForegroundColor Green
exit 0

# Create a Desktop shortcut that starts the whole platform in one click.
#
# Why this file is UTF-8 **with** BOM (unlike the .cmd scripts, which must be
# pure ASCII): the shortcut name contains Chinese, and Windows PowerShell 5.1
# decodes a BOM-less .ps1 as ANSI (GBK on this machine). The same file would
# then read differently under PowerShell 7 (which assumes UTF-8), so the name
# would silently come out as mojibake on one of them. A BOM removes the guess.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\make-shortcut.ps1
#   ... -Name "My Name" -Target <path to .cmd> -Force
#
# The shortcut points at start-all.cmd, which starts both services and opens
# the browser; it is safe to double-click while the services are already up.

param(
    [string] $Name = '启动财经舆情平台',
    [string] $Target = '',
    [string] $IconPath = '',
    [string] $Destination = '',
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if ([string]::IsNullOrWhiteSpace($Target)) {
    $Target = Join-Path $repoRoot 'scripts\start-all.cmd'
}
if (-not (Test-Path -LiteralPath $Target)) {
    throw "target script not found: $Target"
}
$Target = (Resolve-Path -LiteralPath $Target).Path

if ([string]::IsNullOrWhiteSpace($IconPath)) {
    $candidate = Join-Path $repoRoot 'assets\app.ico'
    if (Test-Path -LiteralPath $candidate) { $IconPath = $candidate }
}

if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = [Environment]::GetFolderPath('Desktop')
}
if (-not (Test-Path -LiteralPath $Destination)) {
    throw "desktop folder not found: $Destination"
}

$lnkPath = Join-Path $Destination ($Name + '.lnk')
if ((Test-Path -LiteralPath $lnkPath) -and -not $Force) {
    throw "shortcut already exists: $lnkPath (pass -Force to overwrite)"
}

# Target the .cmd directly instead of cmd.exe /c "..." -- Windows already runs
# .cmd files through cmd.exe, and hand-quoting a path with spaces into
# Arguments is the classic way to produce a shortcut that flashes and dies.
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $Target
$lnk.WorkingDirectory = $repoRoot
$lnk.Description = 'Start backend (:8000) and frontend (:5173), then open the browser'
$lnk.WindowStyle = 1
# Only assign IconLocation when we actually have an icon. Assigning an empty
# string leaves a literal ",0" behind, and Windows then falls back to the
# generic shortcut icon instead of inheriting the .cmd one.
$hasIcon = (-not [string]::IsNullOrWhiteSpace($IconPath)) -and (Test-Path -LiteralPath $IconPath)
if ($hasIcon) {
    $lnk.IconLocation = (Resolve-Path -LiteralPath $IconPath).Path + ',0'
}
$lnk.Save()

Write-Host "[shortcut] created: $lnkPath"
Write-Host "[shortcut] target : $Target"
if ($hasIcon) {
    Write-Host "[shortcut] icon   : $((Resolve-Path -LiteralPath $IconPath).Path)"
} else {
    Write-Host "[shortcut] icon   : (none - run tools\make_icon.py to generate assets\app.ico)"
}

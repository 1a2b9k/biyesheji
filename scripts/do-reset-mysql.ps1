# Reset the MySQL 8.0 root password.
# Run elevated. Logs everything to D:\biyesheji\.tmp\mysql-reset.log
#
# Usage (from an elevated prompt):
#   powershell -NoProfile -ExecutionPolicy Bypass -File do-reset-mysql.ps1 -NewPassword 'xxx'
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads BOM-less
# UTF-8 as the OEM codepage (GBK on this machine), which corrupts parsing
# of any non-ASCII byte and the script dies before its first statement.
#
# NOTE: the password is a parameter, never a literal -- this file is in git.

param(
    [Parameter(Mandatory = $true)]
    [string]$NewPassword
)

$ErrorActionPreference = 'Continue'

$LOG = 'D:\biyesheji\.tmp\mysql-reset.log'
Set-Content -LiteralPath $LOG -Value 'mysql root password reset - start' -Encoding UTF8

function Log([string]$m) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -LiteralPath $LOG -Value $line -Encoding UTF8
}

$BASE    = 'D:\MySQL\MySQL Server 8.0'
$MYSQLD  = Join-Path $BASE 'bin\mysqld.exe'
$MYSQL   = Join-Path $BASE 'bin\mysql.exe'
$MYINI   = Join-Path $BASE 'my.ini'
$DATADIR = Join-Path $BASE 'Data'
$INIT    = Join-Path $DATADIR 'zz-reset-init.sql'

$isAdmin = (New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Log "elevated=$isAdmin"
if (-not $isAdmin) { Log 'ERROR: not elevated'; exit 1 }

Log "mysqld exists = $(Test-Path $MYSQLD)"
Log "my.ini exists = $(Test-Path $MYINI)"
Log "datadir exists = $(Test-Path $DATADIR)"

# --- 1. stop the service ------------------------------------------------
Log 'stopping MySQL80...'
$o = & net stop MySQL80 2>&1
Log ('net stop -> ' + ($o -join ' | '))
Start-Sleep -Seconds 3

# --- 2. write the init file --------------------------------------------
$sql = "ALTER USER 'root'@'localhost' IDENTIFIED BY '$NewPassword';"
Set-Content -LiteralPath $INIT -Value $sql -Encoding ASCII
Log "init file written: $INIT"

# --- 3. start mysqld with --init-file ----------------------------------
$outFile = 'D:\biyesheji\.tmp\mysqld-out.log'
$errFile = 'D:\biyesheji\.tmp\mysqld-err.log'
Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue

$argLine = '--defaults-file="{0}" --init-file="{1}"' -f $MYINI, $INIT
Log "starting mysqld $argLine"

$proc = Start-Process -FilePath $MYSQLD -ArgumentList $argLine -PassThru `
    -WindowStyle Hidden -RedirectStandardOutput $outFile -RedirectStandardError $errFile
Log "mysqld pid=$($proc.Id)"

# --- 4. wait for the port ----------------------------------------------
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) {
        Log "mysqld exited early, code=$($proc.ExitCode)"
        break
    }
    $t = Test-NetConnection -ComputerName 127.0.0.1 -Port 3306 -WarningAction SilentlyContinue
    if ($t.TcpTestSucceeded) { $ready = $true; Log "port 3306 up after ${i}s"; break }
}

if (-not $ready) {
    Log 'ERROR: mysqld did not come up'
    foreach ($f in @($errFile, $outFile)) {
        if (Test-Path $f) {
            $body = (Get-Content -LiteralPath $f -Raw) -replace "`r?`n", ' | '
            Log ("$([IO.Path]::GetFileName($f)): " + $body)
        }
    }
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
    Log 'restoring service...'
    & net start MySQL80 2>&1 | Out-Null
    Remove-Item -LiteralPath $INIT -Force -ErrorAction SilentlyContinue
    exit 1
}

# --- 5. verify the new password ---------------------------------------
$o = & $MYSQL -uroot "-p$NewPassword" -e 'SELECT VERSION() AS v;' 2>&1
$code = $LASTEXITCODE
Log "verify exit=$code -> $($o -join ' | ')"

# --- 6. shut the temporary instance down ------------------------------
if ($code -eq 0) {
    & $MYSQL -uroot "-p$NewPassword" -e 'SHUTDOWN;' 2>&1 | Out-Null
    Log 'graceful shutdown requested'
    Start-Sleep -Seconds 6
}
if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Log 'force killed mysqld'
    Start-Sleep -Seconds 3
}

# --- 7. remove the init file (it holds the password) ------------------
Remove-Item -LiteralPath $INIT -Force -ErrorAction SilentlyContinue
Log 'init file removed'

# --- 8. restart the service -------------------------------------------
Log 'starting MySQL80...'
$o = & net start MySQL80 2>&1
Log ('net start -> ' + ($o -join ' | '))
Start-Sleep -Seconds 5

# --- 9. final verification --------------------------------------------
$o = & $MYSQL -uroot "-p$NewPassword" -e 'SELECT VERSION() AS v;' 2>&1
$code2 = $LASTEXITCODE
Log "final verify exit=$code2 -> $($o -join ' | ')"

if ($code2 -eq 0) { Log 'SUCCESS' } else { Log 'FAILED' }
exit $code2

@echo off
REM One-click launcher: backend (:8000) + frontend (:5173) + open the browser.
REM Safe to run twice: services that are already up are detected and skipped.
REM NOTE: keep this file ASCII-only -- see test-all.cmd for why.
setlocal EnableExtensions
cd /d "%~dp0.."

echo [start-all] workspace: %CD%

REM ---------------------------------------------------------------- backend
call :http_ok "http://127.0.0.1:8000/api/health" 2
if not errorlevel 1 (
    echo [start-all] backend already up on 8000
    goto :frontend
)

echo [start-all] starting backend window ...
start "fin-backend" cmd /k call "%~dp0start-backend.cmd"
call :wait_http "http://127.0.0.1:8000/api/health" 90
if errorlevel 1 (
    echo [start-all] ERROR: backend not ready after 90s.
    echo [start-all] check the "fin-backend" window for the traceback.
    pause
    exit /b 1
)
echo [start-all] backend ready

REM ---------------------------------------------------------------- frontend
:frontend
call :http_ok "http://127.0.0.1:5173/" 2
if not errorlevel 1 (
    echo [start-all] frontend already up on 5173
    goto :open
)

echo [start-all] starting frontend window ...
start "fin-frontend" cmd /k call "%~dp0start-frontend.cmd"
call :wait_http "http://127.0.0.1:5173/" 120
if errorlevel 1 (
    echo [start-all] ERROR: frontend not ready after 120s.
    echo [start-all] check the "fin-frontend" window for the error.
    pause
    exit /b 1
)
echo [start-all] frontend ready

REM ---------------------------------------------------------------- browser
:open
echo [start-all] opening http://127.0.0.1:5173/
start "" "http://127.0.0.1:5173/"
echo.
echo [start-all] done. Close the two service windows to stop.
REM ping instead of timeout: timeout needs stdin and dies under redirection,
REM which makes this script untestable from a harness.
ping -n 4 127.0.0.1 >nul 2>&1
exit /b 0

REM ---------------------------------------------------------------- helpers
REM %1 = url, %2 = timeout seconds. exit 0 when HTTP 200.
:http_ok
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$r = $null; try { $r = Invoke-WebRequest -Uri '%~1' -UseBasicParsing -TimeoutSec %~2 } catch {}; if ($r -ne $null -and $r.StatusCode -eq 200) { exit 0 }; exit 1"
exit /b %ERRORLEVEL%

REM %1 = url, %2 = max seconds. exit 0 once HTTP 200, polling once a second.
:wait_http
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$u = '%~1'; for ($i = 0; $i -lt %~2; $i++) { $r = $null; try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 2 } catch {}; if ($r -ne $null -and $r.StatusCode -eq 200) { exit 0 }; Start-Sleep -Seconds 1 }; exit 1"
exit /b %ERRORLEVEL%

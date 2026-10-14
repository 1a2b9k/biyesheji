@echo off
REM Start the backend (FastAPI). First run creates the DB and seeds default stocks.
REM API docs: http://127.0.0.1:8000/docs
REM NOTE: keep this file ASCII-only -- see test-all.cmd for why.
REM
REM Why --reload is NOT on by default:
REM   uvicorn's reloader spawns a child process and talks to it over a named
REM   pipe. Under the DSH sandbox, restricted processes are not allowed to
REM   open named pipes, so the reloader dies in a loop with
REM   "PermissionError: [WinError 5]" and the server never binds the port.
REM   Plain (no-reload) mode runs in a single process and works fine.
REM   To opt in when running outside the sandbox:  set RELOAD=1

cd /d "%~dp0.."

set RELOAD_FLAG=
if "%RELOAD%"=="1" set RELOAD_FLAG=--reload

echo [backend] http://127.0.0.1:8000   (API docs at /docs)
if defined RELOAD_FLAG echo [backend] auto-reload ENABLED
".python\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 %RELOAD_FLAG% --app-dir backend

echo.
echo [backend] stopped (exit code %ERRORLEVEL%)
pause

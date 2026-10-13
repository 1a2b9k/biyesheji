@echo off
REM Start the backend (FastAPI). First run creates the DB and seeds default stocks.
REM API docs: http://127.0.0.1:8000/docs
REM NOTE: keep this file ASCII-only -- see test-all.cmd for why.

cd /d "%~dp0.."

echo [backend] http://127.0.0.1:8000   (API docs at /docs)
".python\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --app-dir backend

pause

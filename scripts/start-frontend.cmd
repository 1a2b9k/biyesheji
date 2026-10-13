@echo off
REM Start the frontend (Vite dev server). Proxies /api to the backend on :8000.
REM Start the backend first.
REM NOTE: keep this file ASCII-only -- see test-all.cmd for why.

cd /d "%~dp0..\frontend"

set npm_config_cache=%~dp0..\.npm-cache

echo [frontend] http://127.0.0.1:5173
node --import ../tools/vite-sandbox-shim.mjs node_modules/vite/bin/vite.js --port 5173 --host 127.0.0.1

pause

@echo off
REM Run all tests (backend + frontend). Must be green before delivery.
REM NOTE: keep this file ASCII-only -- cmd.exe reads it in the OEM codepage
REM (GBK on this machine) and non-ASCII bytes corrupt parsing.

cd /d "%~dp0.."

echo ============================================================
echo  [1/2] backend tests (pytest)
echo ============================================================
".python\python.exe" -m pytest -q --rootdir=backend backend\tests
if errorlevel 1 goto fail

echo.
echo ============================================================
echo  [2/2] frontend tests (vitest)
echo ============================================================
node --import ./tools/vite-sandbox-shim.mjs frontend/node_modules/vitest/vitest.mjs run --root frontend
if errorlevel 1 goto fail

echo.
echo ============================================================
echo  ALL TESTS PASSED
echo ============================================================
exit /b 0

:fail
echo.
echo ============================================================
echo  TESTS FAILED - see output above
echo ============================================================
exit /b 1

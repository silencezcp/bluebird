@echo off
rem Run every test with the bundled Python 3.8 interpreter.
setlocal
set "PY=D:\DSH_Workspaces\Ftp\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"
echo ==== session / transfer round trip ====
"%PY%" tests\test_ftp_roundtrip.py || goto :fail
echo.
echo ==== user interface smoke test ====
"%PY%" tests\test_ui_smoke.py || goto :fail
echo.
echo ==== command line client ====
"%PY%" tests\test_cli.py || goto :fail
echo.
echo ==== packaged build (skipped when dist\ is absent) ====
if exist "dist\BlueBird\BlueBird.exe" (
    dist\BlueBird\BlueBird.exe --selftest || goto :fail
) else (
    echo dist\BlueBird\BlueBird.exe not built - run build_exe.cmd first
)
if exist "dist\BlueBird\BlueBird-cli.exe" (
    dist\BlueBird\BlueBird-cli.exe selftest || goto :fail
) else (
    echo dist\BlueBird\BlueBird-cli.exe not built - run build_exe.cmd first
)
echo.
echo All test suites passed.
exit /b 0
:fail
echo.
echo TESTS FAILED
exit /b 1

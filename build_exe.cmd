@echo off
rem ---------------------------------------------------------------------------
rem  Build dist\BlueBird\ with the bundled Python 3.8.
rem
rem  Produces dist\BlueBird\BlueBird.exe plus docs\ and the Qt runtime.
rem  docs\ carries the user manual only; the developer manual stays here.
rem ---------------------------------------------------------------------------
setlocal
set "PY=D:\DSH_Workspaces\Ftp\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

echo === regenerating the icon and version resource ===
rem this also refreshes the copy the manuals embed, so the two cannot differ
"%PY%" tools\make_icon.py || goto :fail

echo.
echo === rebuilding the manuals (user + developer) ===
rem only the user manual is copied into dist\ by the spec
"%PY%" tools\build_manual.py || goto :fail

echo.
echo === packaging with PyInstaller ===
"%PY%" -m PyInstaller --clean --noconfirm packaging\BlueBird.spec || goto :fail

echo.
echo === self test of the packaged GUI ===
dist\BlueBird\BlueBird.exe --selftest || goto :fail
echo.
type dist\BlueBird\bluebird-startup.log 2>nul

echo.
echo Build finished: dist\BlueBird\BlueBird.exe
exit /b 0

:fail
echo.
echo BUILD FAILED
exit /b 1

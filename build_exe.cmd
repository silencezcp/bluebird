@echo off
rem ---------------------------------------------------------------------------
rem  Build dist\BlueBird\ with the bundled Python 3.8.
rem
rem  Produces two programs:
rem     dist\BlueBird\BlueBird.exe      the graphical client
rem     dist\BlueBird\BlueBird-cli.exe  the command line client
rem  plus docs\ (the user manual) and the Qt runtime.
rem ---------------------------------------------------------------------------
setlocal
set "PY=D:\DSH_Workspaces\Ftp\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

echo === regenerating the icon and version resource ===
rem this also refreshes the copy the manual embeds, so the two cannot differ
"%PY%" tools\make_icon.py || goto :fail

echo.
echo === rebuilding the user manual with the new icon ===
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
echo === self test of the packaged command line client ===
dist\BlueBird\BlueBird-cli.exe selftest || goto :fail

echo.
echo Build finished:
echo   dist\BlueBird\BlueBird.exe      graphical client
echo   dist\BlueBird\BlueBird-cli.exe  command line client
exit /b 0

:fail
echo.
echo BUILD FAILED
exit /b 1

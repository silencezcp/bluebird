@echo off
rem ---------------------------------------------------------------------------
rem  Build dist\BlueBird\BlueBird.exe with the bundled Python 3.8.
rem  Output: dist\BlueBird\  (exe + docs\ + Qt runtime)
rem ---------------------------------------------------------------------------
setlocal
set "PY=D:\DSH_Workspaces\Ftp\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

echo === rebuilding the user manual ===
"%PY%" tools\build_manual.py || goto :fail

echo.
echo === regenerating the icon and version resource ===
"%PY%" tools\make_icon.py || goto :fail

echo.
echo === packaging with PyInstaller ===
"%PY%" -m PyInstaller --clean --noconfirm packaging\BlueBird.spec || goto :fail

echo.
echo === self test of the packaged build ===
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

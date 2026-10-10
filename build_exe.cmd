@echo off
rem ---------------------------------------------------------------------------
rem  Build dist\NacreFTP\NacreFTP.exe with the bundled Python 3.8.
rem  Output: dist\NacreFTP\  (exe + docs\ + Qt runtime)
rem ---------------------------------------------------------------------------
setlocal
set "PY=D:\DSH_Workspaces\Ftp\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

echo === rebuilding the user manual ===
"%PY%" tools\build_manual.py || goto :fail

echo.
echo === packaging with PyInstaller ===
"%PY%" -m PyInstaller --clean --noconfirm packaging\NacreFTP.spec || goto :fail

echo.
echo === self test of the packaged build ===
dist\NacreFTP\NacreFTP.exe --selftest || goto :fail
echo.
type dist\NacreFTP\nacreftp-startup.log 2>nul

echo.
echo Build finished: dist\NacreFTP\NacreFTP.exe
exit /b 0

:fail
echo.
echo BUILD FAILED
exit /b 1

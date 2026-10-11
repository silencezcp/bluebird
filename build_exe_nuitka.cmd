@echo off
rem ---------------------------------------------------------------------------
rem  Build dist-nuitka\BlueBird.dist\ with Nuitka (MSVC 2019).
rem
rem  This is the Nuitka counterpart of build_exe.cmd / packaging\BlueBird.spec,
rem  kept alongside it so the two packagers can be compared on one source tree.
rem  Unlike PyInstaller this is a real compile, so expect many minutes.
rem
rem  Anything given to this script is passed straight to tools\build_nuitka.py,
rem  for example:  build_exe_nuitka.cmd --jobs 4
rem                build_exe_nuitka.cmd --dry-run
rem                build_exe_nuitka.cmd --no-patch --skip-manual
rem ---------------------------------------------------------------------------
setlocal
set "PY=D:\DSH_Workspaces\Ftp\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

echo === Nuitka build of BlueBird ===
echo.
"%PY%" tools\build_nuitka.py %*
if errorlevel 1 goto :fail

echo.
echo === done ===
echo   dist-nuitka\BlueBird.dist\BlueBird.exe
echo.
echo   compare with the PyInstaller build in dist\BlueBird\ :
echo     dist\BlueBird\BlueBird.exe --selftest --log
echo     dist-nuitka\BlueBird.dist\BlueBird.exe --selftest --log
exit /b 0

:fail
echo.
echo === BUILD FAILED ===
exit /b 1

@echo off
rem ---------------------------------------------------------------------------
rem  Pack the built client into a single archive for distribution.
rem
rem  7z / LZMA2 instead of zip: on this bundle that is 74 MB against 108 MB for
rem  the same ~45 seconds.  Pass "zip" to also produce a .zip, which Windows can
rem  open without any extra tool installed.
rem
rem  Usage:  pack_release.cmd [zip]
rem ---------------------------------------------------------------------------
setlocal
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "DIST=%HERE%\dist\BlueBird"
set "OUT=%HERE%\dist\release"
set "SEVENZIP=C:\Program Files\7-Zip\7z.exe"

if not exist "%DIST%\BlueBird.exe" (
    echo ERROR: %DIST%\BlueBird.exe not found - run build_exe.cmd first
    exit /b 1
)
if not exist "%SEVENZIP%" (
    echo ERROR: 7-Zip not found at "%SEVENZIP%"
    echo        Install it, or point SEVENZIP in this script at 7z.exe.
    exit /b 1
)

rem the version, read straight out of the package source
set "VERSION=unknown"
for /f "tokens=3" %%v in ('findstr /r /c:"^__version__" "%HERE%\ftpclient\__init__.py"') do set "VERSION=%%~v"

if not exist "%OUT%" mkdir "%OUT%"

rem what is being packed, summed with a plain cmd loop - no shell escaping games
set "SRCKB=0"
for /f "usebackq" %%s in (`powershell -NoProfile -Command "(Get-ChildItem -LiteralPath '%DIST%' -Recurse -File | Measure-Object -Property Length -Sum).Sum"`) do set "SRCBYTES=%%s"
for /f "usebackq" %%s in (`powershell -NoProfile -Command "[math]::Round((Get-ChildItem -LiteralPath '%DIST%' -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1)"`) do set "SRCMB=%%s"

echo === packing BlueBird %VERSION% ===
echo   source: %SRCMB% MB   %DIST%
echo.

set "SEVEN=%OUT%\BlueBird-%VERSION%-win64.7z"
if exist "%SEVEN%" del /q "%SEVEN%"
echo === 7z / LZMA2 ultra ===
"%SEVENZIP%" a -t7z -m0=lzma2 -mx=9 -md=64m -mfb=273 -ms=on "%SEVEN%" "%DIST%\*" -bso0 -bsp0
if errorlevel 1 ( echo ERROR: 7z failed & exit /b 1 )

if /i "%~1"=="zip" (
    setlocal enabledelayedexpansion
    set "ZIPF=%OUT%\BlueBird-%VERSION%-win64.zip"
    if exist "!ZIPF!" del /q "!ZIPF!"
    echo.
    echo === zip / deflate max ===
    "%SEVENZIP%" a -tzip -mx=9 "!ZIPF!" "%DIST%\*" -bso0 -bsp0
    if errorlevel 1 ( echo ERROR: zip failed & endlocal & exit /b 1 )
    endlocal
)

echo.
echo === result ===
powershell -NoProfile -Command "Get-ChildItem '%OUT%' -File | Sort-Object Length -Descending | ForEach-Object { '  {0,7:N1} MB  {1}' -f ($_.Length/1MB), $_.Name }"
echo.
echo   %OUT%
exit /b 0

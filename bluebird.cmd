@echo off
rem ---------------------------------------------------------------------------
rem  BlueBird command line client.
rem
rem    bluebird.cmd ls sftp://user@host:22
rem    bluebird.cmd get sftp://user@host/pub/file.bin -d C:\Temp
rem    bluebird.cmd --help
rem
rem  Uses the bundled Python 3.8 when it is present.
rem ---------------------------------------------------------------------------
setlocal
set "PY=D:\DSH_Workspaces\Ftp\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0bluebird.py" %*
endlocal

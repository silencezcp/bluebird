@echo off
rem ---------------------------------------------------------------------------
rem  Smart FTP command line client.
rem
rem    smartftp.cmd ls sftp://user@host:22
rem    smartftp.cmd get sftp://user@host/pub/file.bin -d C:\Temp
rem    smartftp.cmd --help
rem
rem  Uses the bundled Python 3.8 when it is present.
rem ---------------------------------------------------------------------------
setlocal
set "PY=D:\DSH_Workspaces\Ftp\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0smartftp.py" %*
endlocal

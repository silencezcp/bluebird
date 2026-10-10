@echo off
rem ---------------------------------------------------------------------------
rem  Launch the Smart FTP client with the bundled Python 3.8 interpreter.
rem  Any arguments are forwarded, e.g.  run.cmd sftp://user@host:22
rem ---------------------------------------------------------------------------
setlocal
set "PY=D:\DSH_Workspaces\Ftp\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0run.py" %*
endlocal

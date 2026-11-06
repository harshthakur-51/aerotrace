@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-local.ps1" %*
set "runExitCode=%ERRORLEVEL%"
if not "%runExitCode%"=="0" echo Local simulator failed. See the message above.
pause
exit /b %runExitCode%

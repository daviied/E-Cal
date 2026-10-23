@echo off
rem Keeps CalcVault in sync while the HP Prime is plugged in: changes on the
rem calculator or the web app are copied across within a few seconds. Close
rem HP's Connectivity Kit first. Leave this window open; close it to stop.
cd /d "%~dp0"
call :findpython || goto :end
%PY% -c "import hid" 2>nul || %PY% -m pip install --user -r requirements.txt
%PY% -m cvsync live %*
goto :end

:findpython
rem "python" on Windows can be the Microsoft Store's placeholder, which does
rem not run anything, so the py launcher and the usual install folders come first.
set PY=
where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set PY=py -3
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set PY="%%D\python.exe"
if not defined PY python -c "import sys" >nul 2>nul && set PY=python
if not defined PY (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/
  exit /b 1
)
exit /b 0

:end
echo.
pause

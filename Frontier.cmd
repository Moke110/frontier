@echo off
setlocal
 title Frontier
set "FRONTIER_CODE=%~dp0."
set "FRONTIER_ARCHIVE=%~dp0..\frontier-archive"
set "FRONTIER_PYTHON=%FRONTIER_CODE%\runtime\python.exe"
if exist "%FRONTIER_PYTHON%" goto ready
set "FRONTIER_PYTHON=%FRONTIER_CODE%\.venv\Scripts\python.exe"
if exist "%FRONTIER_PYTHON%" goto ready
set "FRONTIER_PYTHON=%FRONTIER_CODE%\.frontier\.venv\Scripts\python.exe"
if exist "%FRONTIER_PYTHON%" goto ready
echo Frontier Python runtime is missing.
goto failed
:ready
cd /d "%FRONTIER_CODE%"
if not "%~1"=="" goto command
"%FRONTIER_PYTHON%" -X utf8 -m hostrun.cli --code "%FRONTIER_CODE%" --archive "%FRONTIER_ARCHIVE%" console install
if errorlevel 1 goto failed
"%FRONTIER_PYTHON%" -c "import tkinter"
if errorlevel 1 goto failed
start "Frontier" "%FRONTIER_PYTHON:python.exe=pythonw.exe%" -X utf8 -m hostrun.desktop --code "%FRONTIER_CODE%" --archive "%FRONTIER_ARCHIVE%"
exit /b 0
:command
"%FRONTIER_PYTHON%" -X utf8 -m hostrun.cli --code "%FRONTIER_CODE%" --archive "%FRONTIER_ARCHIVE%" %*
exit /b %errorlevel%
:failed
echo.
echo Frontier could not start. Please review the error above.
pause
exit /b 1

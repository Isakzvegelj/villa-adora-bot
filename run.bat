@echo off
setlocal

set PYTHON=
if exist "%~dp0.venv424\Scripts\python.exe" (
  set "PYTHON=%~dp0.venv424\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

echo [run] using: %PYTHON%
"%PYTHON%" "%~dp0app.py"

endlocal

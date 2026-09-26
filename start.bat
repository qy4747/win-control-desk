@echo off
rem Source launcher: prefer Python 3.12; accept a newer installed interpreter.
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
py -3.12 -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>nul
if not errorlevel 1 (
  py -3.12 server.py --launcher %*
  exit /b
)
py -3 -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>nul
if not errorlevel 1 (
  py -3 server.py --launcher %*
  exit /b
)
python -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>nul
if not errorlevel 1 (
  python server.py --launcher %*
  exit /b
)
echo Python 3.12 or newer is required. Install Python and its launcher or add python to PATH.
exit /b 1

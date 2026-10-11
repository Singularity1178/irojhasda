@echo off
REM ------------------------------------------------------------------
REM  Iroha Desktop Pet  -  launches "sonnet 5.5 iroha_pet.py"
REM  Uses the Python 3.13 virtual environment next to this script.
REM ------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "PY="
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" if not defined PY set "PY=.venv\Scripts\python.exe"
if not defined PY set "PY=py -3.13"

echo Using: %PY%
%PY% -c "import sys; print(sys.version)"
echo.

%PY% "%~dp0sonnet 5.5 iroha_pet.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo Exited with code %RC%.
    pause
)
endlocal

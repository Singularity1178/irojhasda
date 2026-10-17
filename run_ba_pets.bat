@echo off
REM ------------------------------------------------------------------
REM  Desktop Pets - Blue Archive look, single screen
REM  One character per .glb in the model\ folder, all locked to one monitor.
REM  Uses the Python 3.13 virtual environment next to this script.
REM
REM  Any options are passed straight through, e.g.
REM    run_ba_pets.bat --dump
REM    run_ba_pets.bat --screen primary
REM    run_ba_pets.bat --model model\Iroha.glb --scale 1.2 --fps 60
REM    run_ba_pets.bat --debug-tags      (what the system watcher sees)
REM
REM  run_anim_debug.bat is the same app with --anim-debug: the animation playing on
REM  each character written over her. Test bench, not normal use.
REM ------------------------------------------------------------------
setlocal
title Desktop Pets - Blue Archive
cd /d "%~dp0"

set "PY="
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY set "PY=py -3.13"

echo Using: %PY%

REM The renderer needs moderngl; say so plainly instead of a traceback.
"%PY%" -c "import moderngl" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: this Python cannot import moderngl.
    echo   Fix with:  %PY% -m pip install moderngl PySide6 numpy
    echo.
    pause
    exit /b 1
)

%PY% "%~dp0multi_single_screen_pet_ba.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo Exited with code %RC%.
    pause
)
endlocal
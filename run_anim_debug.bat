@echo off
REM ------------------------------------------------------------------
REM  Desktop Pets - ANIMATION DEBUGGER  (test bench, not normal use)
REM  The whole app, with the exact animation playing written over
REM  every character. Any options are passed straight through, e.g.
REM    run_anim_debug.bat --screen primary
REM    run_anim_debug.bat --model model\Ayane.glb --scale 1.4
REM    run_anim_debug.bat --rag-debug      (both overlays at once)
REM ------------------------------------------------------------------
setlocal
title Desktop Pets - ANIMATION DEBUG
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

"%PY%" "%~dp0anim_debug_view.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo Exited with code %RC%.
    pause
)
endlocal
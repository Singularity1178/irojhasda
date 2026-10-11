@echo off
REM ==================================================================
REM  Universal .py launcher  -  pick a script, run it on the Python 3.13 venv
REM ==================================================================
REM
REM  Usage
REM    run_any_py.bat                        pick a .py with a file dialog
REM    run_any_py.bat script.py [args...]    run a .py directly
REM                                           (dragging a .py onto this file
REM                                            works too)
REM
REM  Launcher options  (must come before the script name)
REM    --no-pause   exit straight away instead of pausing at the end
REM    --list       only list the .py files next to this launcher
REM
REM  Everything after the script name is forwarded to the script, e.g.
REM    run_any_py.bat "New Text Document.py" --dump
REM    run_any_py.bat multi_single_screen_pet_ba.py --screen primary
REM
REM  When you pick the script from the dialog/menu, put the arguments for
REM  that script after a bare "--":
REM    run_any_py.bat -- --dump
REM
REM  Interpreter : venv\Scripts\python.exe next to this file (Python 3.13)
REM  Folder      : the script runs with its own folder as working directory
REM
setlocal EnableExtensions EnableDelayedExpansion
title Run any .py - Python 3.13 venv
cd /d "%~dp0"

REM ---- 1. find the Python 3.13 venv ---------------------------------
set "PY="
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY for /f "usebackq delims=" %%I in (`py -3.13 -c "import sys;print(sys.executable)" 2^>nul`) do if not defined PY set "PY=%%I"
if not defined PY goto no_python

REM ---- 2. parse arguments -------------------------------------------
set "PAUSE_AT_END=1"
set "LISTONLY="
set "PICK="
set "FWD="

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--no-pause" (set "PAUSE_AT_END=" & shift & goto parse_args)
if /i "%~1"=="--list"    (set "LISTONLY=1"    & shift & goto parse_args)
if /i "%~1"=="--help"    goto usage
if /i "%~1"=="-h"        goto usage
if "%~1"=="--"          (shift & goto collect_fwd)
if exist "%~1" (set "PICK=%~1" & shift & goto collect_args)
goto bad_option

:collect_fwd
REM  a bare "--" means: I will pick the script interactively, but these
REM  arguments still belong to whatever I pick.
if "%~1"=="" goto args_done
set "FWD=%FWD% %1"
shift
goto collect_fwd

:collect_args
if "%~1"=="" goto args_done
set "FWD=%FWD% %1"
shift
goto collect_args

:args_done

REM ---- 3. --list ----------------------------------------------------
if defined LISTONLY goto do_list

REM ---- 4. nothing given: file dialog, then console menu -------------
if defined PICK goto have_pick
call :gui_pick
if defined PICK goto have_pick
call :menu_pick

:have_pick
if not defined PICK goto quit

REM ---- 5. resolve the file ------------------------------------------
if not exist "%PICK%" goto missing
for %%I in ("%PICK%") do set "SCRIPTFULL=%%~fI"
for %%I in ("%SCRIPTFULL%") do set "WORKDIR=%%~dpI"

REM ---- 6. syntax check before spending time on it -------------------
"%PY%" -c "import ast,sys;p=sys.argv[1];ast.parse(open(p,encoding='utf-8-sig').read(),p);print('  Syntax      : OK')" "%SCRIPTFULL%"
if errorlevel 1 goto syntax_bad

REM ---- 7. run it ----------------------------------------------------
cd /d "%WORKDIR%"
echo.
echo  ------------------------------------------------------------
echo   Interpreter : %PY%
"%PY%" -c "import sys;print('  Python      :',sys.version.split()[0])"
echo   Script      : %SCRIPTFULL%
echo   Folder      : %CD%
echo   Arguments   : %FWD%
echo  ------------------------------------------------------------
echo.
"%PY%" "%SCRIPTFULL%" %FWD%
set "RC=%ERRORLEVEL%"
echo.
echo  [exit code %RC%]
goto finish

REM ---- exits -------------------------------------------------------
:finish
if defined PAUSE_AT_END pause
endlocal & exit /b %RC%

:quit
if defined PAUSE_AT_END pause
endlocal & exit /b 0

:fail
echo.
if defined PAUSE_AT_END (echo   Press any key to close. & pause >nul)
endlocal & exit /b 1

:no_python
echo.
echo  ERROR: no Python 3.13 interpreter found.
echo.
echo  Create the venv next to this launcher with
echo      py -3.13 -m venv "%~dp0venv"
goto fail

:missing
echo.
echo  ERROR: "%PICK%" does not exist.
goto fail

:syntax_bad
echo.
echo  ERROR: that file is not valid Python, so it was not run.
echo         Fix the syntax error above and try again.
goto fail

:bad_option
echo.
echo  ERROR: unknown option "%~1"
goto usage

:do_list
echo.
echo  Python scripts in "%~dp0":
echo.
dir /b /a:-d "%~dp0*.py" 2>nul
set "PAUSE_AT_END="
goto quit

:usage
echo.
echo  Usage:
echo    run_any_py.bat                       pick a .py with a file dialog
echo    run_any_py.bat script.py [args...]   run a .py directly
echo.
echo  Options (before the script name):
echo    --no-pause                           do not pause when it finishes
echo    --list                               list the .py files next to this bat
echo.
echo  Examples:
echo    run_any_py.bat
echo    run_any_py.bat --no-pause "New Text Document.py" --dump
echo    run_any_py.bat multi_single_screen_pet_ba.py --screen primary
echo    run_any_py.bat -- --dump             pick a script, pass it --dump
goto fail

REM ==================================================================
REM  Subroutines
REM ==================================================================

:gui_pick
REM  A real Windows file dialog. Falls through silently if there is no
REM  GUI (server, plain console) - the menu below takes over.
set "BATDIR=%~dp0"
set "PICKFILE=%TEMP%\run_any_py_pick.txt"
if exist "%PICKFILE%" del /f /q "%PICKFILE%" >nul 2>&1
set "PSCODE=Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.OpenFileDialog; $d.Title='Pick a Python script to run'; $d.Filter='Python scripts (*.py)|*.py|All files (*.*)|*.*'; $d.InitialDirectory=$env:BATDIR.TrimEnd([char]92); if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){[IO.File]::WriteAllText($env:PICKFILE,$d.FileName)}"
where powershell >nul 2>&1
if errorlevel 1 exit /b 0
powershell -NoProfile -STA -ExecutionPolicy Bypass -Command "Invoke-Expression $env:PSCODE"
if not exist "%PICKFILE%" exit /b 0
set /p "PICK=" <"%PICKFILE%"
del /f /q "%PICKFILE%" >nul 2>&1
exit /b 0

:menu_pick

:menu_pick
set "TRIES=0"
:menu_loop
cls
echo.
echo  ============================================================
echo   Pick a Python script
echo  ============================================================
echo.
set "N=0"
for %%F in ("%~dp0*.py") do (
    set /a "N+=1"
    echo     !N!  %%~nxF
    set "FN!N!=%%~nxF"
)
if not defined N goto menu_manual
echo.
echo     A  type a path instead
echo     Q  quit
echo.
set /p "PICKN=   Number / letter: "
REM  "set /p" leaves a trailing CR behind when the input is piped in
set "PICKN=!PICKN: =!"
set /a "TRIES+=1"
if !TRIES! GTR 12 goto menu_give_up
if not defined PICKN goto menu_loop
if /i "!PICKN:~0,1!"=="q" goto quit
if /i "!PICKN:~0,1!"=="a" goto menu_manual
set "NUM="
set /a "NUM=!PICKN!" 2>nul
if not defined NUM goto menu_bad
set "PICK=!FN%NUM%!"
if defined PICK exit /b 0
goto menu_bad

:menu_manual
set /p "MAN=   Full path: "
set "MAN=!MAN:"=!"
if not defined MAN goto menu_loop
set /a "TRIES+=1"
if !TRIES! GTR 12 goto menu_give_up
if exist "!MAN!" (set "PICK=!MAN!" & exit /b 0)
echo.
echo   Not found: !MAN!
>nul 2>&1 ping -n 3 127.0.0.1
goto menu_loop

:menu_bad
echo.
echo   Pick a number from the list above.
>nul 2>&1 ping -n 3 127.0.0.1
goto menu_loop

:menu_give_up
echo.
echo   No script chosen.
goto quit

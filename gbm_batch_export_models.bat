@echo off
setlocal EnableExtensions

if "%~1"=="" (
    echo Drag one or more .arc files or folders onto this script.
    echo.
    echo You can also run it from a terminal:
    echo   %~nx0 file1.arc file2.arc
    pause
    exit /b 1
)

python "%~dp0tools\gbm_batch.py" %*
if errorlevel 1 pause

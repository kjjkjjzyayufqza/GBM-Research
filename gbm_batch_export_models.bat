@echo off
setlocal EnableExtensions

if "%~1"=="" (
    set "DEFAULT_CH=%~dp0..\com.bandainamcoent.gb_jp\files\dlc\archive\ch"
    if not exist "%DEFAULT_CH%" (
        echo Drag one or more .arc files or folders onto this script.
        echo.
        echo You can also run it from a terminal:
        echo   %~nx0 file1.arc file2.arc
        pause
        exit /b 1
    )
    echo No input passed; exporting model-only archives from:
    echo   %DEFAULT_CH%
    echo.
    python "%~dp0tools\gbm_batch.py" "%DEFAULT_CH%" -o "%~dp0out\ch_models"
) else (
    python "%~dp0tools\gbm_batch.py" %*
)
if errorlevel 1 pause

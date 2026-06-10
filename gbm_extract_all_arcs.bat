@echo off
setlocal
python "%~dp0tools\gbm_batch.py" --extract-only %*
if errorlevel 1 pause

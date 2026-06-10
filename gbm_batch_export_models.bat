@echo off
setlocal
python "%~dp0tools\gbm_batch.py" %*
if errorlevel 1 pause

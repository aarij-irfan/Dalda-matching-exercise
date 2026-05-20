@echo off
title Dalda Outlet Matcher
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not on PATH.
    echo Install Python 3.10+ from https://www.python.org/
    echo Tick "Add python.exe to PATH" during install.
    pause
    exit /b 1
)

python setup_and_run.py
if errorlevel 1 pause

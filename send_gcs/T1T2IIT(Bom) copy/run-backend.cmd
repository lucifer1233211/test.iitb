@echo off
cd /d "%~dp0drone_backend"
".venv\Scripts\python.exe" main.py 1>"%~dp0backend.log" 2>"%~dp0backend-error.log"

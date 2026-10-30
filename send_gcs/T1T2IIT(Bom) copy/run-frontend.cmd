@echo off
cd /d "%~dp0"
npm.cmd run dev 1>"%~dp0frontend.log" 2>"%~dp0frontend-error.log"

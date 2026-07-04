@echo off
cd /d "%~dp0"
auto-poster.exe --once >> logs\scheduler.log 2>&1

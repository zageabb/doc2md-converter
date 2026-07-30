@echo off
cd /d "%~dp0"
py -m doc2md_watcher --gui %*

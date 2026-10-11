@echo off
rem jp-lesson-builder launcher for Windows (PowerShell / cmd).
rem   .\lesson check 2026-09-20
rem Python lookup order: .venv (if it still runs) -> py launcher -> python
rem (python/python3 may resolve to the Microsoft Store stub, so try py first)
rem NOTE: keep this file ASCII-only with CRLF line endings.
setlocal
set "HERE=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist "%HERE%.venv\Scripts\python.exe" goto findpy
"%HERE%.venv\Scripts\python.exe" -c "import jinja2" >nul 2>&1
if not errorlevel 1 goto venv
echo [lesson] .venv is broken; falling back to the system Python. Run: lesson setup 1>&2
:findpy
where py >nul 2>&1 && goto launcher
python "%HERE%lesson.py" %*
exit /b %ERRORLEVEL%
:venv
"%HERE%.venv\Scripts\python.exe" "%HERE%lesson.py" %*
exit /b %ERRORLEVEL%
:launcher
py -3 "%HERE%lesson.py" %*
exit /b %ERRORLEVEL%

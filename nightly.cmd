@echo off
rem jp-lesson-builder nightly job: researches today's news and builds the lesson
rem with Claude Code (headless). Called by Windows Task Scheduler
rem ("lesson schedule install"); double-click to run it now.
rem Options: [YYYY-MM-DD] [--force] [--commit] [--no-notify] [--dry-run] [--smoke]
rem NOTE: keep this file ASCII-only with CRLF line endings.
setlocal
cd /d "%~dp0"
call "%~dp0lesson.cmd" nightly %*
exit /b %ERRORLEVEL%

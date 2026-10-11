#!/usr/bin/env sh
# jp-lesson-builder ランチャー（macOS / Linux / Windows の Git Bash 用）
#   ./lesson.sh check 2026-09-20
# Python は .venv（壊れていなければ）→ py ランチャー → python3 → python の順に探す。
# （Windows では python / python3 が Microsoft Store のスタブに化けることがあるため py を先に試す）
HERE=$(cd "$(dirname "$0")" && pwd)
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
for c in "$HERE/.venv/bin/python" "$HERE/.venv/Scripts/python.exe"; do
  if [ -x "$c" ]; then
    if "$c" -c "import jinja2" >/dev/null 2>&1; then exec "$c" "$HERE/lesson.py" "$@"; fi
    echo "[lesson] .venv が壊れています。システムの Python で続行します（lesson setup で作り直せます）" >&2
  fi
done
if command -v py >/dev/null 2>&1; then exec py -3 "$HERE/lesson.py" "$@"; fi
if command -v python3 >/dev/null 2>&1; then exec python3 "$HERE/lesson.py" "$@"; fi
exec python "$HERE/lesson.py" "$@"

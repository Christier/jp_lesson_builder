# macOS / Linux 向けの薄いラッパー。中身はすべて lesson.py にある。
# Windows では make は不要：.\lesson.cmd <コマンド> [日付]  /  Git Bash なら ./lesson.sh
DATE ?= $(shell date +%Y-%m-%d)
PYTHON ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: new merge build validate check all record finish open review rebuild doctor setup test nightly clean

new merge build validate check record finish open review:  ## 例: make check DATE=2026-09-20
	$(PYTHON) lesson.py $@ $(DATE)

all: check

rebuild doctor setup test nightly:
	$(PYTHON) lesson.py $@

clean:
	rm -f dist/*.html

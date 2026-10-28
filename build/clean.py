#!/usr/bin/env python3
"""
clean.py — 古い教材を片付けて容量を節約する。

    lesson clean [--keep-days 3] [--dry-run]

今日を含めて直近 N 日（既定3日）より古いものを消す:
  content/<日付>.json             教材データ（git の履歴には残るので、必要なら戻せる）
  dist/N1日语学习-<和暦>.html       生成したHTML
  drafts/<日付>/                  下書き
  logs/<日付>-nightly.log・<日付>-claude.jsonl   夜間実行のログ（いちばん容量を食う）

残すもの:
  data/（テーマ履歴・語彙インデックス）… 同じテーマ・語彙を繰り返さないために必要
  notes/、logs/latest.json、tmp/ のバックアップ
  いちばん新しい教材（夜間実行が何日も失敗していても、最後の1日分は必ず残す）

消す前に、その教材の「語（よみ）」を data/readings.json に移す（自動振り仮名の辞書が痩せないように）。
戻し方: git log --oneline -- content/2026-10-20.json → git checkout <その前のコミット> -- content/2026-10-20.json
"""
from __future__ import annotations

import re
import shutil
import sys
from datetime import date as Date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DEFAULT_PATHS, Paths, UserError, load_json, write_text_atomic  # noqa: E402

_DIST = re.compile(r"^N1日语学习-(\d{4})年(\d{1,2})月(\d{1,2})日\.html$")
_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _date(s: str) -> Date | None:
    try:
        return Date.fromisoformat(s)
    except ValueError:
        return None


def plan(paths: Paths = DEFAULT_PATHS, keep_days: int = 3, today: Date | None = None) -> dict:
    """消す対象の一覧（まだ何も消さない）"""
    if keep_days < 1:
        raise UserError("--keep-days は 1 以上にしてください")
    today = today or Date.today()
    cutoff = today - timedelta(days=keep_days - 1)  # この日以降は残す
    lessons = sorted(d for f in paths.content.glob("*.json") if (d := _date(f.stem)))
    newest = lessons[-1] if lessons else None

    def old(d: Date | None) -> bool:
        return d is not None and d < cutoff and d != newest

    p: dict = {"cutoff": cutoff, "newest": newest, "content": [], "dist": [], "drafts": [], "logs": []}
    p["content"] = [paths.content_file(d.isoformat()) for d in lessons if old(d)]
    for f in sorted(paths.dist.glob("N1日语学习-*.html")):
        m = _DIST.match(f.name)
        if m and old(Date(int(m.group(1)), int(m.group(2)), int(m.group(3)))):
            p["dist"].append(f)
    if paths.drafts.exists():
        p["drafts"] = [d for d in sorted(paths.drafts.iterdir()) if d.is_dir() and old(_date(d.name))]
    if paths.logs.exists():
        for f in sorted(paths.logs.iterdir()):
            m = _DATED.match(f.name)
            if f.is_file() and m and old(_date(m.group(1))):
                p["logs"].append(f)
    p["kept"] = [d.isoformat() for d in lessons if not old(d)]
    return p


def _size(path: Path) -> int:
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return path.stat().st_size if path.exists() else 0


def save_readings(paths: Paths, files: list[Path]) -> int:
    """消す教材の読みを data/readings.json に足す。足した語数を返す"""
    import build
    saved = build.saved_readings(paths)
    before = len(saved)
    for f in files:
        try:
            build.collect_readings(load_json(f), saved)
        except UserError:
            continue
    if len(saved) != before:
        entries = {k: [list(x) for x in v] for k, v in sorted(saved.items())}
        body = {"_comment": "片付けた（削除した）教材から引き継いだ振り仮名の辞書。lesson clean が更新する。手で編集しない。",
                "entries": entries}
        import json
        write_text_atomic(paths.data / "readings.json", json.dumps(body, ensure_ascii=False, indent=1) + "\n")
    return len(saved) - before


def main(keep_days: int = 3, paths: Paths = DEFAULT_PATHS, dry_run: bool = False,
         today: Date | None = None, log=print) -> dict:
    p = plan(paths, keep_days, today)
    targets = p["content"] + p["dist"] + p["drafts"] + p["logs"]
    size = sum(_size(t) for t in targets)
    head = "[clean] （dry-run）" if dry_run else "[clean] "
    log(f"{head}{p['cutoff'].isoformat()} より前を片付けます（残す教材: {', '.join(p['kept']) or 'なし'}）")
    for key, label in (("content", "教材データ"), ("dist", "HTML"), ("drafts", "下書き"), ("logs", "ログ")):
        if p[key]:
            log(f"{head}{label} {len(p[key])}件: {', '.join(t.name for t in p[key][:6])}"
                f"{' ほか' if len(p[key]) > 6 else ''}")
    log(f"{head}合計 {len(targets)}件・{size / 1024 / 1024:.1f} MB"
        + ("（実行するには --dry-run を外す）" if dry_run and targets else ""))
    removed = {"content": [], "count": 0, "bytes": size, "readings": 0}
    if dry_run or not targets:
        return removed
    removed["readings"] = save_readings(paths, p["content"])
    for t in targets:
        if t.is_dir():
            shutil.rmtree(t, ignore_errors=True)
        else:
            t.unlink(missing_ok=True)
    removed["content"] = [f"content/{t.name}" for t in p["content"]]
    removed["count"] = len(targets)
    try:
        import build
        build.build_index(paths)  # 一覧と latest.html を作り直す
    except UserError:
        pass
    if removed["readings"]:
        log(f"[clean] 振り仮名の辞書に {removed['readings']} 語を引き継ぎました（data/readings.json）")
    return removed


if __name__ == "__main__":
    from common import setup_stdio
    setup_stdio()
    try:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 3, dry_run="--dry-run" in sys.argv)
    except UserError as e:
        raise SystemExit(f"[clean] ERROR {e}")

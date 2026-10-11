#!/usr/bin/env python3
"""
review.py — data/vocab-index.json を集計して、復習の優先度をMarkdownで出す。

使い方:
    python build/review.py [YYYY-MM-DD]     （基準日。省略時は今日。通常は lesson.py review 経由）

分類（/review コマンドと同じ定義）:
  * 定着候補 … 3回以上登場
  * 要再訪   … 2回登場、最終出現から3週間以上
  * 一度きり … 1回のみ
加えて、content/*.json の index.terms のうち vocab-index に記録されていないもの（記録漏れ）を出す。
"""
from __future__ import annotations

import sys
from datetime import date as Date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DEFAULT_PATHS, Paths, UserError, load_json, parse_date, setup_stdio  # noqa: E402

REVISIT_DAYS = 21


def _md(d: str) -> str:
    try:
        x = Date.fromisoformat(d)
        return f"{x.month}/{x.day}"
    except ValueError:
        return d


def collect(paths: Paths, today: Date) -> dict:
    entries = [e for e in load_json(paths.data / "vocab-index.json").get("entries", []) if isinstance(e, dict)]
    rows = []
    for e in entries:
        seen = sorted(d for d in e.get("seen", []) if isinstance(d, str))
        if not seen:
            continue
        last = Date.fromisoformat(seen[-1])
        rows.append({"term": e.get("term", ""), "kind": e.get("kind", ""), "seen": seen,
                     "n": len(seen), "last": seen[-1], "days": (today - last).days})

    fixed = [x for x in rows if x["n"] >= 3]
    revisit = [x for x in rows if x["n"] == 2 and x["days"] >= REVISIT_DAYS]
    once = [x for x in rows if x["n"] == 1]
    recent2 = [x for x in rows if x["n"] == 2 and x["days"] < REVISIT_DAYS]

    # 記録漏れ：content の index.terms にあるのに vocab-index にその日付がない
    recorded = {(x["term"], d) for x in rows for d in x["seen"]}
    missing = []
    for f in sorted(paths.content.glob("*.json")):
        try:
            c = load_json(f)
        except UserError:
            continue
        idx = c.get("index") if isinstance(c, dict) else None
        if not isinstance(idx, dict):
            continue
        d = f.stem
        for t in idx.get("terms", []):
            term = str(t.get("term", "")).strip() if isinstance(t, dict) else ""
            if term and (term, d) not in recorded:
                missing.append((d, term))

    # 次回の優先候補：要再訪（古い順）→ 一度きり（古い順）→ 2回・最近
    priority = (sorted(revisit, key=lambda x: x["last"]) + sorted(once, key=lambda x: x["last"])
                + sorted(recent2, key=lambda x: x["last"]))
    return {"fixed": fixed, "revisit": revisit, "once": once, "recent2": recent2,
            "missing": missing, "priority": priority[:10], "total": len(rows)}


def to_markdown(r: dict, today: Date) -> str:
    def table(items):
        if not items:
            return "（なし）\n"
        out = ["| 語 | 種別 | 回数 | 登場日 | 最終から |", "|---|---|---|---|---|"]
        for x in sorted(items, key=lambda x: (-x["n"], x["last"])):
            out.append(f"| {x['term']} | {x['kind']} | {x['n']} | {'・'.join(_md(d) for d in x['seen'])} | {x['days']}日 |")
        return "\n".join(out) + "\n"

    lines = [f"# 語彙復習レポート（基準日 {today.isoformat()}・登録 {r['total']}語）", ""]
    lines += ["## 定着候補（3回以上）", "", table(r["fixed"])]
    lines += [f"## 要再訪（2回・最終から{REVISIT_DAYS}日以上）", "", table(r["revisit"])]
    lines += ["## 一度きり（1回のみ）", "", table(r["once"])]
    lines += [f"## 2回・最近（{REVISIT_DAYS}日未満）", "", table(r["recent2"])]
    lines += ["## 次回教材で優先的に再登場させる候補", ""]
    lines += [f"{i}. {x['term']}（{x['n']}回・最終 {_md(x['last'])}）" for i, x in enumerate(r["priority"], 1)] or ["（なし）"]
    lines += ["", "## 記録漏れ（content の index.terms にあるが vocab-index に未記録）", ""]
    lines += [f"- {d}: {t}" for d, t in r["missing"]] or ["（なし）"]
    return "\n".join(lines) + "\n"


def main(date: str | None, paths: Paths = DEFAULT_PATHS) -> str:
    today = parse_date(date)
    md = to_markdown(collect(paths, today), today)
    print(md, end="")
    return md


if __name__ == "__main__":
    setup_stdio()
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else None)
    except UserError as e:
        raise SystemExit(f"[review] ERROR {e}")

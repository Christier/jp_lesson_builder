#!/usr/bin/env python3
"""
record.py — 完成した教材を data/themes.json と data/vocab-index.json に記録する。

使い方:
    python build/record.py 2026-09-20      （通常は lesson.py record / finish 経由）

・content/<DATE>.json の index（theme / terms）を読む。index.theme がなければ meta.theme_label。
・themes.json   : used に {date, theme, palette} を追加（同じ日付があれば置き換え）。
                  テーマが candidates に完全一致で載っていれば候補から外す。
・vocab-index   : terms を追加。既出語は seen に日付を足し、first を更新。
・何度実行しても同じ結果になる（冪等）。validate に ERROR がある間は記録しない。
・既存ファイルの「1エントリ1行」の書式を保ったまま書き戻す（git の差分が読みやすい）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_PATHS, Paths, UserError, load_json, parse_date, setup_stdio, write_text_atomic,
)


def dumps_compact(obj: dict) -> str:
    """トップレベルの配列は1要素1行、それ以外は通常の JSON で書く。"""
    def one(v) -> str:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    lines = ["{"]
    keys = list(obj)
    for n, k in enumerate(keys):
        v = obj[k]
        comma = "," if n < len(keys) - 1 else ""
        if isinstance(v, list) and v:
            lines.append(f"  {json.dumps(k, ensure_ascii=False)}: [")
            for i, item in enumerate(v):
                if isinstance(item, str):
                    s = json.dumps(item, ensure_ascii=False)
                else:
                    s = one(item)
                lines.append(f"    {s}{',' if i < len(v) - 1 else ''}")
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def plan(c: dict, date: str, themes: dict, vindex: dict, prune: bool = False) -> tuple[dict, dict, list[str]]:
    """記録後の themes / vindex と、変更内容のログを返す（ファイルには書かない）"""
    log: list[str] = []
    themes = json.loads(json.dumps(themes))
    vindex = json.loads(json.dumps(vindex))
    meta = c.get("meta", {})
    idx = c.get("index") if isinstance(c.get("index"), dict) else {}

    # --- themes.json
    theme = (idx.get("theme") or meta.get("theme_label") or "").strip()
    if not theme:
        raise UserError("記録するテーマ名がありません（index.theme か meta.theme_label を書いてください）")
    entry = {"date": date, "theme": theme, "palette": meta.get("palette", "")}
    used = [u for u in themes.get("used", []) if isinstance(u, dict)]
    old = next((u for u in used if u.get("date") == date), None)
    if old == entry:
        log.append(f"themes.json : 変更なし（{theme} / {entry['palette']}）")
    else:
        used = [u for u in used if u.get("date") != date] + [entry]
        used.sort(key=lambda u: u.get("date", ""))
        log.append(f"themes.json : {'更新' if old else '追加'} → {theme} / {entry['palette']}")
    themes["used"] = used

    cands = themes.get("candidates", [])
    for t in {theme, meta.get("theme_label", "")}:
        if t and t in cands:
            cands = [x for x in cands if x != t]
            log.append(f"themes.json : 候補から外した → {t}")
    if "candidates" in themes:
        themes["candidates"] = cands

    # --- vocab-index.json
    entries = [e for e in vindex.get("entries", []) if isinstance(e, dict)]
    by_term = {e.get("term"): e for e in entries}
    terms = [t for t in idx.get("terms", []) if isinstance(t, dict) and str(t.get("term", "")).strip()]
    added, updated = [], []
    wanted = set()
    for t in terms:
        term = str(t["term"]).strip()
        wanted.add(term)
        e = by_term.get(term)
        if e is None:
            e = {"term": term, "first": date, "seen": [date], "kind": t.get("kind", "")}
            entries.append(e)
            by_term[term] = e
            added.append(term)
            continue
        seen = sorted(set(d for d in e.get("seen", []) if isinstance(d, str)) | {date})
        first = min(seen)
        if seen != e.get("seen") or first != e.get("first"):
            e["seen"], e["first"] = seen, first
            updated.append(term)
        if not e.get("kind") and t.get("kind"):
            e["kind"] = t["kind"]

    stale = [e["term"] for e in entries if date in e.get("seen", []) and e.get("term") not in wanted]
    if stale and prune:
        for e in list(entries):
            if e.get("term") in stale:
                e["seen"] = [d for d in e.get("seen", []) if d != date]
                if not e["seen"]:
                    entries.remove(e)
                else:
                    e["first"] = min(e["seen"])
        log.append(f"vocab-index : {date} を外した → {'、'.join(stale)}")
    elif stale:
        log.append(f"vocab-index : 注意 index.terms にないが {date} が記録されている語 → {'、'.join(stale)}"
                   "（不要なら --prune で外す）")

    vindex["entries"] = entries
    if added:
        log.append(f"vocab-index : 新規 {len(added)}語 → {'、'.join(added)}")
    if updated:
        log.append(f"vocab-index : 既出 {len(updated)}語に日付追加 → {'、'.join(updated)}")
    if not added and not updated and not (stale and prune):
        log.append("vocab-index : 変更なし" + ("" if terms else "（index.terms が空）"))
    return themes, vindex, log


def main(date: str | None, paths: Paths = DEFAULT_PATHS, prune: bool = False, force: bool = False) -> int:
    from validate import print_report, validate  # 循環 import を避けるためここで読む

    d = parse_date(date).isoformat()
    r = validate(d, paths)
    if not r.ok and not force:
        print_report(r, d)
        print("[record] ERROR が残っているので記録しません（validate を通してから実行）")
        return 1

    c = load_json(paths.content_file(d))
    tpath, vpath = paths.data / "themes.json", paths.data / "vocab-index.json"
    themes, vindex = load_json(tpath), load_json(vpath)
    new_t, new_v, log = plan(c, d, themes, vindex, prune=prune)

    if new_t != themes:
        write_text_atomic(tpath, dumps_compact(new_t))
    if new_v != vindex:
        write_text_atomic(vpath, dumps_compact(new_v))
    for line in log:
        print(f"[record] {line}")
    return 0


if __name__ == "__main__":
    setup_stdio()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) > 1:
        raise SystemExit("usage: python build/record.py [YYYY-MM-DD] [--prune] [--force]")
    try:
        sys.exit(main(args[0] if args else None, prune="--prune" in sys.argv, force="--force" in sys.argv))
    except UserError as e:
        raise SystemExit(f"[record] ERROR {e}")

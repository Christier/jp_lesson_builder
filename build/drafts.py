#!/usr/bin/env python3
"""
drafts.py — 分割して書いた下書きを content/<DATE>.json に結合する。

使い方:
    lesson merge 2026-10-17                 drafts/2026-10-17/*.json を名前順に結合
    lesson merge 2026-10-17 a.json b.json   指定したファイルを順に結合

教材のJSONは60KBを超えるので、1回の書き込みで全部を書くと出力が途中で切れることがある。
news.json / scene.json / ext.json のように分けて書き、ここで1つにまとめる。

結合のルール:
  * トップレベルのキー（meta / news / scene / ext / index）ごとに、既存の値へ「浅く」上書きする。
    例：{"news": {"articles": [...]}} は news.articles だけを差し替え、news.audio_note は残す。
  * ファイル名が news.json なのに中身に "news" キーがなければ、中身全体を news とみなす。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DEFAULT_PATHS, Paths, UserError, load_json, parse_date, write_json  # noqa: E402

SECTIONS = ("meta", "news", "scene", "ext", "index")


def merge_into(base: dict, part: dict, name: str = "") -> list[str]:
    """part を base に結合し、変更したキーの一覧を返す"""
    stem = Path(name).stem
    if stem in SECTIONS and stem not in part:
        part = {stem: part}
    unknown = [k for k in part if k not in SECTIONS]
    if unknown:
        raise UserError(f"{name}: 未知のトップレベルキー {unknown}（使えるのは {', '.join(SECTIONS)}）")
    changed = []
    for k, v in part.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k].update(v)
            changed += [f"{k}.{kk}" for kk in v]
        else:
            base[k] = v
            changed.append(k)
    return changed


def main(date: str | None, files: list[str] | None = None, paths: Paths = DEFAULT_PATHS) -> Path:
    d = parse_date(date).isoformat()
    dst = paths.content_file(d)
    if not dst.exists():
        raise UserError(f"{dst} がありません。先に `lesson new {d}` で雛形を作ってください。")
    if files:
        srcs = [Path(f) for f in files]
    else:
        folder = paths.drafts / d
        srcs = sorted(folder.glob("*.json"))
        if not srcs:
            raise UserError(f"{folder} に下書き（*.json）がありません")

    base = load_json(dst)
    for src in srcs:
        part = load_json(src)  # 壊れていれば行・列つきの UserError
        if not isinstance(part, dict):
            raise UserError(f"{src.name}: JSONのトップレベルがオブジェクトではありません")
        changed = merge_into(base, part, src.name)
        print(f"[merge] {src.name} → {', '.join(changed)}")
    write_json(dst, base)
    print(f"[merge] OK  {dst}（次: lesson check {d}）")
    return dst


if __name__ == "__main__":
    from common import setup_stdio
    setup_stdio()
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else None, sys.argv[2:] or None)
    except UserError as e:
        raise SystemExit(f"[merge] ERROR {e}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"[merge] ERROR {e}")

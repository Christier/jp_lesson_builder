#!/usr/bin/env python3
"""
lesson.py — jp-lesson-builder の統一コマンド（Windows / macOS / Linux 共通）。

    lesson new      [DATE]   雛形 content/<DATE>.json を作る
    lesson build    [DATE]   JSON → dist/N1日语学习-<和暦>.html
    lesson validate [DATE]   入力JSONと出力HTMLを検証
    lesson check    [DATE]   build → validate（執筆中はこれを繰り返す）
    lesson record   [DATE]   data/themes.json・vocab-index.json に記録（ERROR 0 のときだけ）
    lesson finish   [DATE]   build → validate → record（仕上げ）
    lesson open     [DATE]   生成HTMLをブラウザで開く
    lesson rebuild           content/*.json を全部ビルド＆検証（テンプレート改修後の回帰確認）
    lesson review   [DATE]   語彙の復習レポート（--save で notes/ に保存）
    lesson doctor            実行環境の点検
    lesson setup             .venv を作って依存を入れる
    lesson test              自動テストを実行

DATE は YYYY-MM-DD。省略すると今日。
起動は lesson.cmd（Windows）か ./lesson.sh（macOS / Linux / Git Bash）から。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "build"))

from common import DEFAULT_PATHS, UserError, load_json, parse_date, setup_stdio  # noqa: E402

P = DEFAULT_PATHS


# ---------------------------------------------------------------- 各コマンド
def cmd_new(a) -> int:
    import new_content
    new_content.main(a.date, P)
    return 0


def cmd_build(a) -> int:
    import build
    build.main(_date(a), P)
    return 0


def cmd_validate(a) -> int:
    import validate
    return validate.main(_date(a), P)


def cmd_check(a) -> int:
    cmd_build(a)
    return cmd_validate(a)


def cmd_record(a) -> int:
    import record
    return record.main(_date(a), P, prune=a.prune, force=a.force)


def cmd_finish(a) -> int:
    import record
    cmd_build(a)
    rc = cmd_validate(a)
    if rc:
        print("[finish] ERROR が残っているので記録しません")
        return rc
    return record.main(_date(a), P)


def cmd_open(a) -> int:
    d = _date(a)
    c = load_json(P.content_file(d))
    out = P.dist_file(c["meta"]["date_jp"])
    if not out.exists():
        raise UserError(f"{out.name} がありません。先に `lesson build {d}` を実行してください。")
    print(f"[open] {out}")
    if sys.platform.startswith("win"):
        os.startfile(str(out))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(out)], check=False)
    else:
        webbrowser.open(out.as_uri())
    return 0


def cmd_rebuild(a) -> int:
    import build
    import validate
    files = sorted(P.content.glob("*.json"))
    if not files:
        print("[rebuild] content/*.json がありません")
        return 0
    failed = 0
    for f in files:
        d = f.stem
        try:
            build.main(d, P, quiet=True)
            r = validate.validate(d, P)
        except UserError as e:
            print(f"  NG  {d}  build失敗: {e}")
            failed += 1
            continue
        mark = "OK" if r.ok else "NG"
        failed += 0 if r.ok else 1
        print(f"  {mark}  {d}  ERROR {len(r.errors)} / WARN {len(r.warns)}")
        if a.verbose or not r.ok:
            for e in r.errors:
                print(f"        ERROR {e}")
    print(f"\n[rebuild] {len(files)}件中 NG {failed}件")
    return 1 if failed else 0


def cmd_review(a) -> int:
    import review
    md = review.main(a.date, P)
    if a.save:
        from common import write_text_atomic
        out = P.notes / f"review-{parse_date(a.date).isoformat()}.md"
        write_text_atomic(out, md)
        print(f"\n[review] 保存しました → {out}")
    return 0


def cmd_doctor(a) -> int:
    ok = True
    print(f"Python  : {sys.version.split()[0]}  ({sys.executable})")
    if sys.version_info < (3, 10):
        print("  NG  Python 3.10 以上が必要です")
        ok = False
    venv = HERE / ".venv"
    print(f".venv   : {'あり' if venv.exists() else 'なし（lesson setup で作成）'}"
          f"{'（使用中）' if Path(sys.prefix).resolve() == venv.resolve() else ''}")
    try:
        import jinja2
        print(f"Jinja2  : {jinja2.__version__}")
    except ImportError:
        print("  NG  Jinja2 がありません → lesson setup")
        ok = False
    print(f"stdout  : {sys.stdout.encoding}")
    for name in ("palettes.json", "themes.json", "vocab-index.json"):
        try:
            load_json(P.data / name)
            print(f"  OK  data/{name}")
        except UserError as e:
            print(f"  NG  {e}")
            ok = False
    for name in ("base.html.j2", "styles.css.j2", "app.js"):
        exists = (P.templates / name).exists()
        print(f"  {'OK' if exists else 'NG'}  templates/{name}")
        ok &= exists
    n = len(list(P.content.glob("*.json")))
    print(f"content : {n}件")
    print("\n[doctor] " + ("問題なし" if ok else "要対応の項目があります"))
    return 0 if ok else 1


def cmd_setup(a) -> int:
    venv = HERE / ".venv"
    if not venv.exists():
        print(f"[setup] 仮想環境を作成: {venv}", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    print("[setup] 依存をインストール: requirements.txt", flush=True)
    subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                    "-r", str(HERE / "requirements.txt")], check=True)
    return subprocess.run([str(py), str(HERE / "lesson.py"), "doctor"]).returncode


def cmd_test(a) -> int:
    import unittest
    suite = unittest.defaultTestLoader.discover(str(HERE / "tests"))
    res = unittest.TextTestRunner(verbosity=2 if a.verbose else 1).run(suite)
    return 0 if res.wasSuccessful() else 1


# ---------------------------------------------------------------- 引数
def _date(a) -> str:
    return parse_date(getattr(a, "date", None)).isoformat()


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lesson", description="日本語N1教材の日次生成ツール",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")

    def add(name, fn, help_, date=True):
        p = sub.add_parser(name, help=help_)
        if date:
            p.add_argument("date", nargs="?", help="YYYY-MM-DD（省略時は今日）")
        p.set_defaults(fn=fn)
        return p

    add("new", cmd_new, "雛形 content/<DATE>.json を作る")
    add("build", cmd_build, "JSON → HTML")
    add("validate", cmd_validate, "入力JSONと出力HTMLを検証")
    add("check", cmd_check, "build → validate")
    p = add("record", cmd_record, "data/themes.json・vocab-index.json に記録")
    p.add_argument("--prune", action="store_true", help="index.terms から消した語の日付を vocab-index からも外す")
    p.add_argument("--force", action="store_true", help="validate に ERROR があっても記録する")
    add("finish", cmd_finish, "build → validate → record")
    add("open", cmd_open, "生成HTMLをブラウザで開く")
    p = add("rebuild", cmd_rebuild, "content/*.json を全部ビルド＆検証", date=False)
    p.add_argument("-v", "--verbose", action="store_true")
    p = add("review", cmd_review, "語彙の復習レポート")
    p.add_argument("--save", action="store_true", help="notes/review-<DATE>.md に保存")
    add("doctor", cmd_doctor, "実行環境の点検", date=False)
    add("setup", cmd_setup, ".venv を作って依存を入れる", date=False)
    p = add("test", cmd_test, "自動テストを実行", date=False)
    p.add_argument("-v", "--verbose", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    setup_stdio()
    ap = parser()
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 2
    try:
        return a.fn(a) or 0
    except UserError as e:
        print(f"[{a.cmd}] ERROR {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"[{a.cmd}] ERROR コマンドが失敗しました: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""
common.py — build / validate / new_content / record が共有する部品。

* パス解決（テスト時は別ディレクトリを渡せるよう Paths にまとめる）
* 軽量マークアップの正規表現
* Windows コンソール（cp932）でも落ちない標準出力の設定
* 日付の解釈、和暦表記、出力ファイル名
* 改行コード LF 固定・アトミックな書き込み（途中で切れたファイルを残さない）
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WEEK = "月火水木金土日"

# {{v:t1a|ヘクトパスカル}} / {{g:t1e|〜にかけて}} / {{k:970}} / {{b:重要}} / {{br}}
TOKEN = re.compile(r"\{\{(v|g|k|b|br)(?::([^|}]*)(?:\|([^}]*))?)?\}\}")

# ツールチップIDに使える文字（onclick / id 属性に安全に埋め込めるもの）
TIP_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT

    @property
    def content(self) -> Path:
        return self.root / "content"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def dist(self) -> Path:
        return self.root / "dist"

    @property
    def templates(self) -> Path:
        return self.root / "templates"

    @property
    def notes(self) -> Path:
        return self.root / "notes"

    def content_file(self, date: str) -> Path:
        return self.content / f"{date}.json"

    def dist_file(self, date_jp: str) -> Path:
        return self.dist / f"N1日语学习-{date_jp}.html"


DEFAULT_PATHS = Paths()


class UserError(Exception):
    """利用者が直せる種類のエラー（トレースバックを出さずにメッセージだけ表示する）"""


# ---------------------------------------------------------------- 標準出力
def setup_stdio() -> None:
    """Windows の cp932 コンソールでも絵文字・中国語で落ちないようにする。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# ---------------------------------------------------------------- 日付
def parse_date(s: str | None) -> Date:
    """'YYYY-MM-DD' を解釈する。None / 空なら今日。"""
    if not s:
        return Date.today()
    try:
        return Date.fromisoformat(s.strip())
    except ValueError:
        raise UserError(f"日付 '{s}' を解釈できません。YYYY-MM-DD 形式で指定してください（例: 2026-09-20）")


def date_jp(d: Date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def weekday_jp(d: Date) -> str:
    return WEEK[d.weekday()]


# ---------------------------------------------------------------- JSON / ファイル
def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise UserError(f"{path} がありません")
    except json.JSONDecodeError as e:
        raise UserError(f"{path.name} のJSONが壊れています（{e.lineno}行{e.colno}列）: {e.msg}")


def write_text_atomic(path: Path, text: str) -> None:
    """一時ファイルに書いてから置き換える。改行は常に LF。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: Path, obj) -> None:
    write_text_atomic(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------- マークアップ
def strip_markup(text: str) -> str:
    """マークアップとHTMLタグを除いた素のテキスト（字数計測・TTS用）"""
    def repl(m: re.Match) -> str:
        kind, a, b = m.group(1), m.group(2), m.group(3)
        if kind == "br":
            return ""
        if kind in ("v", "g"):
            return b if b is not None else (a or "")
        return a or ""
    s = TOKEN.sub(repl, text)
    return re.sub(r"<[^>]+>", "", s)

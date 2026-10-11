#!/usr/bin/env python3
"""
validate.py — 入力JSONと出力HTMLを検証する。

使い方:
    python build/validate.py 2026-09-20      （通常は lesson.py validate / check 経由）

ここで落ちる＝教材として不完全。Claude Code は ERROR がゼロになるまで直すこと。
WARN は「意図的ならそのままでよい」もの。INFO は参考情報。

どんなに壊れたJSONを渡しても例外で止まらず、ERROR として報告することを保証する。
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_PATHS, TIP_ID, TOKEN, Paths, UserError, date_jp, load_json, parse_date,
    setup_stdio, strip_markup, weekday_jp,
)
from new_content import PLACEHOLDERS  # noqa: E402

# 本文の目安（CLAUDE.md と揃える）
ARTICLE_CHARS = (450, 800)        # 450〜700字が目安。800字超は長すぎ
ARTICLE_HIGHLIGHTS = (12, 20)
ARTICLE_VOCAB_MIN = 6
TURNS_MIN_ERROR, TURNS_MIN, TURNS_MAX = 16, 18, 24
NOTE_RATIO = 0.8
SCENE_VOCAB_MIN = 20
ILLUST_RANGE = (2, 4)
QUIZ_MIN = 8
EXT_SECTIONS_MIN = 4
HEADLINES_MIN = 5
SIZE_MIN_KB = 60

BADGE_COLORS = {"red", "green", "blue", "amber"}
SECTION_KEYS = {"table": ("headers", "rows"), "cards": ("items",), "info": ("cards",), "note": ("body",)}
TERM_KINDS = {"grammar", "vocab", "adverb", "idiom", "conjunction", "phrase", "business", "keigo",
              "onomatopoeia", "proverb"}

# 生HTMLを書いてよいフィールドで許すタグ
ALLOWED_TAGS = {"a", "b", "strong", "br", "em", "i", "u", "small", "span", "ruby", "rt", "rp",
                "code", "mark", "sub", "sup", "s", "del", "ins", "wbr", "kbd"}
VOID_TAGS = {"br", "wbr", "img", "hr"}
FORBIDDEN_TAGS = {"script", "style", "iframe", "object", "embed", "link", "meta", "html", "head",
                  "body", "form", "input", "textarea", "button", "select", "base"}
COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|(rgb|rgba|hsl|hsla)\([^)]*\)|[a-zA-Z]+)$")
CSS_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.infos: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warns.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


# ------------------------------------------------------------------ 型の安全な取り出し
def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _s(v) -> str:
    return v if isinstance(v, str) else ""


def _type_check(r: Report, obj: dict, key: str, typ: type, where: str, required: bool = True) -> None:
    if key not in obj:
        if required:
            r.err(f"{where}.{key} がありません")
        return
    if not isinstance(obj[key], typ):
        r.err(f"{where}.{key} の型が不正です（{typ.__name__} であるべき）")


def _walk(o, path=""):
    """(パス, 文字列) を列挙する"""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(o, str):
        yield path, o


# ------------------------------------------------------------------ 生HTML・SVGの検査
class _TagCheck(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.unbalanced: list[str] = []
        self.tags: set[str] = set()
        self.bad_attrs: list[str] = []

    def _attrs(self, tag, attrs):
        for k, v in attrs:
            if k.lower().startswith("on"):
                self.bad_attrs.append(f"<{tag} {k}=…>")
            if k.lower() in ("href", "src") and _s(v).strip().lower().startswith("javascript:"):
                self.bad_attrs.append(f"<{tag} {k}=javascript:…>")

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        self._attrs(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.tags.add(tag)
        self._attrs(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if tag not in self.stack:
            self.unbalanced.append(f"</{tag}> に対応する開始タグがありません")
            return
        while self.stack:
            t = self.stack.pop()
            if t == tag:
                break
            self.unbalanced.append(f"<{t}> が閉じられていません")

    def finish(self) -> None:
        self.close()
        self.unbalanced += [f"<{t}> が閉じられていません" for t in self.stack]
        self.stack = []


def check_html_fragment(r: Report, path: str, s: str) -> None:
    if "<" not in s:
        return
    p = _TagCheck()
    try:
        p.feed(s)
        p.finish()
    except Exception as e:  # HTMLParser はほぼ例外を出さないが念のため
        r.err(f"{path}: HTMLとして解釈できません（{e}）")
        return
    for u in p.unbalanced:
        r.err(f"{path}: {u}（以降のレイアウトが崩れます）")
    for a in p.bad_attrs:
        r.err(f"{path}: スクリプト実行につながる属性は使えません → {a}")
    forbidden = p.tags & FORBIDDEN_TAGS
    if forbidden:
        r.err(f"{path}: 使ってはいけないタグ → {sorted(forbidden)}")
    unknown = p.tags - ALLOWED_TAGS - FORBIDDEN_TAGS - VOID_TAGS
    if unknown:
        r.warn(f"{path}: 想定外のタグ {sorted(unknown)}（使えるのは <b> <strong> <br> <a> など）")


def check_svg(r: Report, path: str, svg: str) -> None:
    if not svg.strip():
        r.err(f"{path}: SVGが空です")
        return
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        r.err(f"{path}: SVGが整形式ではありません（{e}）。タグの閉じ忘れ・& の生書きなどを確認")
        return
    if not root.tag.endswith("svg"):
        r.err(f"{path}: ルート要素が <svg> ではありません（<{root.tag}>）")
    elif "viewBox" not in root.attrib:
        r.warn(f"{path}: viewBox がありません（viewBox=\"0 0 220 150\" が基準）")
    if re.search(r"<script|\son\w+\s*=", svg, re.I):
        r.err(f"{path}: SVGにスクリプト／イベント属性は入れられません")


# ------------------------------------------------------------------ 入力JSON
def check_json(r: Report, date: str, paths: Paths) -> dict:
    src = paths.content_file(date)
    if not src.exists():
        r.err(f"content/{date}.json がありません（`lesson new {date}` で作成）")
        return {}
    try:
        c = load_json(src)
    except UserError as e:
        r.err(str(e))
        return {}
    if not isinstance(c, dict):
        r.err("JSONのトップレベルがオブジェクトではありません")
        return {}

    for key in ("meta", "news", "scene", "ext"):
        _type_check(r, c, key, dict, "（トップ）")
    if r.errors:
        return c

    try:
        _check_meta(r, c, date, paths)
        _check_strings(r, c)
        _check_news(r, c)
        _check_scene(r, c)
        _check_ext(r, c)
        _check_index(r, c, date, paths)
    except Exception as e:  # 想定外の型でも検証自体は止めない
        r.err(f"検証中に例外が発生しました（JSONの型が想定外の可能性）: {type(e).__name__}: {e}")
    return c


def _check_meta(r: Report, c: dict, date: str, paths: Paths) -> None:
    meta = c["meta"]
    for key in ("date", "date_jp", "weekday", "theme_label", "palette", "sources"):
        _type_check(r, meta, key, str, "meta")
    _type_check(r, meta, "tabs", dict, "meta")
    _type_check(r, meta, "badges", list, "meta")

    if meta.get("date") != date:
        r.err(f"meta.date（{meta.get('date')}）がファイル名の日付（{date}）と違います")
    d = parse_date(date)
    if isinstance(meta.get("date_jp"), str) and meta["date_jp"] != date_jp(d):
        r.err(f"meta.date_jp が '{meta['date_jp']}' です（正しくは '{date_jp(d)}'。出力ファイル名に使われます）")
    if isinstance(meta.get("weekday"), str) and meta["weekday"] != weekday_jp(d):
        r.err(f"meta.weekday が '{meta['weekday']}' です（{date} は {weekday_jp(d)}曜日）")

    for k in ("news", "scene", "ext"):
        if not _s(_d(meta.get("tabs")).get(k)):
            r.err(f"meta.tabs.{k}（タブ名）がありません")

    for i, b in enumerate(_l(meta.get("badges"))):
        if not isinstance(b, dict) or not _s(b.get("text")):
            r.err(f"meta.badges[{i}] に text がありません")
        elif b.get("color") not in BADGE_COLORS:
            r.warn(f"meta.badges[{i}].color '{b.get('color')}' は未定義（{sorted(BADGE_COLORS)}）")

    # --- バッジの数字と実際の中身のずれ（「18ターン」と書いて20ターンある等）
    n_turns = len(_l(_d(c["scene"]).get("turns")))
    n_arts = len(_l(_d(c["news"]).get("articles")))
    for b in _l(meta.get("badges")):
        text = _s(_d(b).get("text"))
        m = re.search(r"(\d+)\s*ターン", text)
        if m and int(m.group(1)) != n_turns:
            r.warn(f"バッジ『{text}』の {m.group(1)}ターン と実際の会話 {n_turns}ターン が違います")
        m = re.search(r"ニュース\s*(\d+)\s*本", text)
        if m and int(m.group(1)) != n_arts:
            r.warn(f"バッジ『{text}』の {m.group(1)}本 と実際のニュース {n_arts}本 が違います")

    # --- パレット
    palettes = load_json(paths.data / "palettes.json")
    if meta.get("palette") not in palettes:
        r.err(f"meta.palette '{meta.get('palette')}' が palettes.json にありません（{', '.join(palettes)}）")

    # --- 直近と同じ配色・既出テーマを避ける（この日より前の記録だけを見る）
    themes = load_json(paths.data / "themes.json")
    before = sorted((u for u in _l(themes.get("used")) if isinstance(u, dict) and _s(u.get("date")) < date),
                    key=lambda u: u["date"])
    recent = [u.get("palette") for u in before[-3:]]
    if meta.get("palette") in recent:
        r.warn(f"配色 '{meta['palette']}' は直近3回で使用済みです（{recent}）")
    label = _s(meta.get("theme_label")) + " " + _s(_d(c.get("index")).get("theme"))
    for u in before:
        t = _s(u.get("theme"))
        key = t.split("（")[0].strip()
        if key and key in label:
            r.warn(f"会話テーマ '{key}' は {u.get('date')} に使用済みの可能性があります（{t}）")


def _check_strings(r: Report, c: dict) -> None:
    """全文字列フィールドの横断チェック：プレースホルダー残り・生HTML・SVG"""
    leftovers: list[str] = []
    for path, s in _walk(c):
        if any(p in s for p in PLACEHOLDERS) or re.search(r"YYYY年", s):
            leftovers.append(path)
        if path.endswith(".svg") and ".illustrations[" in path:
            check_svg(r, path, s)
            continue
        if re.search(r"\.paragraphs\[\d+\]$", path) or re.search(r"\.turns\[\d+\]\.jp$", path):
            if re.search(r"</?[a-zA-Z][^>]*>", s):
                r.warn(f"{path}: 本文・セリフに生HTMLがあります（エスケープされ、タグがそのまま表示されます）。"
                       "{{b:…}} {{k:…}} {{br}} を使ってください")
            continue
        check_html_fragment(r, path, s)
    if leftovers:
        shown = ", ".join(leftovers[:8]) + (f" ほか{len(leftovers) - 8}箇所" if len(leftovers) > 8 else "")
        r.err(f"雛形のプレースホルダーが残っています → {shown}")


def _check_markup(r: Report, where: str, text: str) -> None:
    cleaned = TOKEN.sub("", text)
    if "{{" in cleaned or "}}" in cleaned:
        i = max(cleaned.find("{{"), cleaned.find("}}"))
        snippet = cleaned[max(0, i - 10):i + 15]
        r.err(f"{where}: 閉じていない／未知のマークアップがあります → …{snippet}…"
              "（使えるのは {{v:id|語}} {{g:id|語}} {{k:語}} {{b:語}} {{br}}）")


def _check_news(r: Report, c: dict) -> None:
    news = c["news"]
    _type_check(r, news, "heading", str, "news")
    _type_check(r, news, "articles", list, "news")
    arts = _l(news.get("articles"))
    if len(arts) != 3:
        r.warn(f"ニュースが{len(arts)}本です（通常は3本）")

    tip_count: dict[str, int] = {}
    for i, a in enumerate(arts, 1):
        where = f"ニュース{i}"
        if not isinstance(a, dict):
            r.err(f"news.articles[{i - 1}] がオブジェクトではありません")
            continue
        for key in ("source", "title", "date_line"):
            if not _s(a.get(key)):
                r.err(f"news.articles[{i - 1}].{key} がありません")
        _type_check(r, a, "paragraphs", list, f"news.articles[{i - 1}]")
        _type_check(r, a, "tooltips", list, f"news.articles[{i - 1}]")
        _type_check(r, a, "vocab_box", dict, f"news.articles[{i - 1}]")
        g = a.get("gradient")
        if g is not None and not (isinstance(g, list) and len(g) >= 2 and all(isinstance(x, str) for x in g[:2])):
            r.err(f"news.articles[{i - 1}].gradient は null か [\"#色1\", \"#色2\"] にしてください")

        paras = [p for p in _l(a.get("paragraphs")) if isinstance(p, str)]
        if len(paras) != len(_l(a.get("paragraphs"))):
            r.err(f"{where}: paragraphs に文字列以外が入っています")
        if not paras:
            r.err(f"{where}: 本文（paragraphs）が空です")
            continue
        for j, p in enumerate(paras, 1):
            _check_markup(r, f"{where} 第{j}段落", p)
        body = "\n".join(paras)

        declared: set[str] = set()
        for k, t in enumerate(_l(a.get("tooltips"))):
            tid, tbody = _s(_d(t).get("id")), _s(_d(t).get("body"))
            if not tid:
                r.err(f"{where}: tooltips[{k}] に id がありません")
                continue
            if not TIP_ID.match(tid):
                r.err(f"{where}: ツールチップID '{tid}' に使えない文字があります（英数字・_・- のみ、先頭は英字）")
            if not tbody:
                r.err(f"{where}: ツールチップ {tid} の body が空です")
            declared.add(tid)
            tip_count[tid] = tip_count.get(tid, 0) + 1

        referenced = {m.group(2) or "" for m in TOKEN.finditer(body) if m.group(1) in ("v", "g")}
        missing, orphan = referenced - declared, declared - referenced
        if missing:
            r.err(f"{where}: 本文が参照しているツールチップが未定義 → {sorted(missing)}")
        if orphan:
            r.err(f"{where}: 定義済みだが本文から参照されていないツールチップ → {sorted(orphan)}")

        lo, hi = ARTICLE_HIGHLIGHTS
        if len(referenced) < lo:
            r.warn(f"{where}: ハイライト語が{len(referenced)}個です（{lo}〜{hi}個が目安）")
        elif len(referenced) > hi:
            r.warn(f"{where}: ハイライト語が{len(referenced)}個です（多すぎると読みにくい。{lo}〜{hi}個が目安）")

        chars = len(strip_markup("".join(paras)))
        lo, hi = ARTICLE_CHARS
        if chars < lo:
            r.warn(f"{where}: 本文が{chars}字です（{lo}〜700字が目安）")
        elif chars > hi:
            r.warn(f"{where}: 本文が{chars}字です（長すぎ。450〜700字が目安）")

        vb = _d(a.get("vocab_box"))
        if not _s(vb.get("title")):
            r.err(f"{where}: vocab_box.title がありません")
        items = _l(vb.get("items"))
        if len(items) < ARTICLE_VOCAB_MIN:
            r.warn(f"{where}: まとめ語彙が{len(items)}個です（{ARTICLE_VOCAB_MIN}個以上が目安）")
        for k, v in enumerate(items):
            v = _d(v)
            if not _s(v.get("jp")) or not _s(v.get("cn")):
                r.err(f"{where}: まとめ語彙[{k}] の jp / cn が空です")
            elif not _s(v.get("ex")):
                r.warn(f"{where}: 語彙『{v.get('jp')}』に転用例文(ex)がありません")

    dup = sorted(k for k, n in tip_count.items() if n > 1)
    if dup:
        r.err(f"ツールチップIDが重複しています（ファイル全体で一意に）→ {dup}")

    heads = _l(news.get("headlines"))
    if len(heads) < HEADLINES_MIN:
        r.warn(f"その他の見出しが{len(heads)}本です（{HEADLINES_MIN}本が目安）")
    for k, h in enumerate(heads):
        h = _d(h)
        if not _s(h.get("jp")):
            r.err(f"news.headlines[{k}].jp が空です")
        elif not _s(h.get("time")) or not _s(h.get("cn")):
            r.warn(f"news.headlines[{k}] の time / cn が空です（『{h.get('jp')}』）")


def _check_scene(r: Report, c: dict) -> None:
    scene = c["scene"]
    for key in ("title", "intro", "dialogue_title", "vocab_heading"):
        if not _s(scene.get(key)):
            r.err(f"scene.{key} がありません")
    _type_check(r, scene, "turns", list, "scene")
    _type_check(r, scene, "vocab", list, "scene")
    _type_check(r, scene, "speaker_colors", dict, "scene", required=False)

    turns = _l(scene.get("turns"))
    if len(turns) < TURNS_MIN_ERROR:
        r.err(f"会話が{len(turns)}ターンです（{TURNS_MIN}〜20ターンが目安、最低{TURNS_MIN_ERROR}）")
    elif len(turns) < TURNS_MIN:
        r.warn(f"会話が{len(turns)}ターンです（{TURNS_MIN}〜20ターンが目安）")
    elif len(turns) > TURNS_MAX:
        r.warn(f"会話が{len(turns)}ターンです（長すぎ。18〜20ターンが目安）")

    for i, t in enumerate(turns, 1):
        if not isinstance(t, dict):
            r.err(f"会話ターン{i}: オブジェクトではありません")
            continue
        for key in ("speaker", "speaker_label", "jp", "cn"):
            if not _s(t.get(key)):
                r.err(f"会話ターン{i}: '{key}' がありません")
        jp = _s(t.get("jp"))
        _check_markup(r, f"会話ターン{i}", jp)
        if any(m.group(1) in ("v", "g") for m in TOKEN.finditer(jp)):
            r.err(f"会話ターン{i}: セリフでは {{{{v:…}}}} / {{{{g:…}}}} は使えません（会話にツールチップはない）。"
                  "{{b:…}} か {{k:…}} を使い、解説は note に書いてください")

    dicts = [t for t in turns if isinstance(t, dict)]
    note_ratio = sum(1 for t in dicts if t.get("note")) / max(len(dicts), 1)
    if dicts and note_ratio < NOTE_RATIO:
        r.warn(f"解説(note)付きのターンが{note_ratio:.0%}です（8割以上が目安）")

    colors = _d(scene.get("speaker_colors"))
    used = {_s(t.get("speaker")) for t in dicts if _s(t.get("speaker"))}
    if used - set(colors):
        r.err(f"speaker_colors に色が未定義の話者 → {sorted(used - set(colors))}")
    for name, col in colors.items():
        if not CSS_IDENT.match(name):
            r.err(f"speaker_colors の話者名 '{name}' は英数字・_・- のみ（CSSクラス名になります）")
        if not isinstance(col, str) or not COLOR.match(col.strip()):
            r.warn(f"speaker_colors.{name} の色 '{col}' が色指定として不正の可能性があります（#rrggbb 推奨）")

    if dicts and not any(t.get("side") == "right" for t in dicts):
        r.warn("自分側（side:right）の発話がありません。左右に振り分けると読みやすくなります")

    vocab = _l(scene.get("vocab"))
    if len(vocab) < SCENE_VOCAB_MIN:
        r.warn(f"場面語彙が{len(vocab)}語です（20〜25語が目安）")
    for k, v in enumerate(vocab):
        if not _s(_d(v).get("jp")) or not _s(_d(v).get("cn")):
            r.err(f"scene.vocab[{k}] の jp / cn が空です")

    ills = _l(scene.get("illustrations"))
    lo, hi = ILLUST_RANGE
    if not lo <= len(ills) <= hi:
        r.warn(f"SVG図解が{len(ills)}枚です（{lo}〜{hi}枚が目安）")
    for k, il in enumerate(ills):
        il = _d(il)
        if "svg" not in il:
            r.err(f"scene.illustrations[{k}].svg がありません")
        for key in ("title", "sub", "note"):
            if key not in il:
                r.err(f"scene.illustrations[{k}].{key} がありません（空文字でも可）")

    if not _s(scene.get("roleplay")):
        r.err("scene.roleplay（ロールプレイ課題）がありません")


def _check_ext(r: Report, c: dict) -> None:
    ext = c["ext"]
    _type_check(r, ext, "sections", list, "ext")
    _type_check(r, ext, "quiz", list, "ext")
    sections = _l(ext.get("sections"))
    has_contrast = False
    for k, s in enumerate(sections):
        if not isinstance(s, dict):
            r.err(f"ext.sections[{k}] がオブジェクトではありません")
            continue
        typ = s.get("type")
        if typ not in SECTION_KEYS:
            r.err(f"ext.sections[{k}].type '{typ}' は未対応です（{', '.join(SECTION_KEYS)} のいずれか）")
            continue
        if not _s(s.get("heading")):
            r.err(f"ext.sections[{k}].heading がありません")
        for key in SECTION_KEYS[typ]:
            if key not in s:
                r.err(f"ext.sections[{k}]（{typ}）に {key} がありません")
        if typ == "table":
            headers, rows = _l(s.get("headers")), _l(s.get("rows"))
            for j, row in enumerate(rows):
                if not isinstance(row, list):
                    r.err(f"ext.sections[{k}].rows[{j}] が配列ではありません")
                elif len(row) != len(headers):
                    r.warn(f"ext.sections[{k}].rows[{j}] のセル数（{len(row)}）が見出し数（{len(headers)}）と違います")
            if re.search(r"カジュアル|フォーマル|⇔", _s(s.get("heading"))):
                has_contrast = True
    if len(sections) < EXT_SECTIONS_MIN:
        r.warn(f"拡張セクションが{len(sections)}個です（4〜6個が目安）")
    if sections and not has_contrast:
        r.warn("カジュアル⇔フォーマルの対照表（type:table、見出しに「カジュアル」「⇔」等）がありません")

    quiz = _l(ext.get("quiz"))
    if len(quiz) < QUIZ_MIN:
        r.err(f"クイズが{len(quiz)}問です（{QUIZ_MIN}問が目安）")
    for k, q in enumerate(quiz):
        if not _s(_d(q).get("q")) or not _s(_d(q).get("a")):
            r.err(f"ext.quiz[{k}] の q / a が空です")

    ch = _s(ext.get("challenge"))
    if not ch:
        r.err("ext.challenge（総合チャレンジ）がありません")
    elif "添削" not in ch:
        r.warn("総合チャレンジが『添削します』で締められていません（毎回の定型）")


def _check_index(r: Report, c: dict, date: str, paths: Paths) -> None:
    """lesson record 用の index と、data/ への記録状況"""
    idx = c.get("index")
    if idx is None:
        r.warn("index（record 用のテーマ名・語彙リスト）がありません。record はテーマ名に meta.theme_label を使い、語彙は記録しません")
    elif not isinstance(idx, dict):
        r.err("index はオブジェクトにしてください（{\"theme\": …, \"terms\": [...]}）")
    else:
        terms = idx.get("terms", [])
        if not isinstance(terms, list):
            r.err("index.terms は配列にしてください")
            terms = []
        if not terms:
            r.warn("index.terms が空です（復習インデックスに載せる重要語彙・文法を5〜10個）")
        seen_terms: set[str] = set()
        for k, t in enumerate(terms):
            term = _s(_d(t).get("term")).strip()
            if not term:
                r.err(f"index.terms[{k}].term が空です")
                continue
            if term in seen_terms:
                r.warn(f"index.terms に '{term}' が重複しています")
            seen_terms.add(term)
            kind = _d(t).get("kind")
            if kind not in TERM_KINDS:
                r.warn(f"index.terms[{k}]（{term}）の kind '{kind}' は未定義（{', '.join(sorted(TERM_KINDS))}）")

        # 既出語の一覧（復習リンクを書いたかの確認用）
        try:
            entries = _l(load_json(paths.data / "vocab-index.json").get("entries"))
        except UserError as e:
            r.err(str(e))
            entries = []
        prior = {_s(e.get("term")): [d for d in _l(e.get("seen")) if isinstance(d, str) and d < date]
                 for e in entries if isinstance(e, dict)}
        again = [f"{t}（{'・'.join(_md(d) for d in prior[t])}）" for t in seen_terms if prior.get(t)]
        if again:
            r.info("既出語（ツールチップに「〇/〇の復習」を書いたか確認）: " + "、".join(sorted(again)))

    themes = load_json(paths.data / "themes.json")
    if not any(_d(u).get("date") == date for u in _l(themes.get("used"))):
        r.info("data/themes.json にまだ記録されていません（完成後に `lesson record` を実行）")


def _md(d: str) -> str:
    try:
        x = parse_date(d)
        return f"{x.month}/{x.day}"
    except UserError:
        return d


# ------------------------------------------------------------------ 出力HTML
def check_html(r: Report, c: dict, date: str, paths: Paths) -> None:
    dj = _s(_d(c.get("meta")).get("date_jp"))
    if not dj:
        return
    out = paths.dist_file(dj)
    if not out.exists():
        r.err(f"{out.name} がありません（先に `lesson build` を実行）")
        return
    src = paths.content_file(date)
    if src.exists() and src.stat().st_mtime > out.stat().st_mtime + 1:
        r.err("JSONがHTMLより新しくなっています（ビルドし直してから検証してください: `lesson check`）")

    s = out.read_text(encoding="utf-8")
    size_kb = len(s.encode("utf-8")) / 1024
    if not s.rstrip().endswith("</html>"):
        r.err("HTMLが </html> で終わっていません（書き込みが途中で切れた可能性）")
    for tab in ("tab-news", "tab-scene", "tab-ext"):
        if f'id="{tab}"' not in s:
            r.err(f"{tab} が出力にありません")
    if 'id="dialogue-full"' not in s:
        r.err("会話全文（TTS用 dialogue-full）が出力にありません")
    if s.count("playTTS(") < 4:
        r.warn("TTSプレーヤーが4つ未満です（ニュース3＋会話1が標準）")
    if re.search(r"\{\{|\{%", s):
        r.err("未処理のテンプレート記法（{{ / {%）が出力に残っています")
    if size_kb < SIZE_MIN_KB:
        r.warn(f"出力が{size_kb:.0f}KBです（通常90〜110KB。内容が薄い可能性）")
    r.info(f"出力: {out.name}（{size_kb:.1f} KB）")


# ------------------------------------------------------------------ 実行
def validate(date: str, paths: Paths = DEFAULT_PATHS, check_output: bool = True) -> Report:
    r = Report()
    try:
        d = parse_date(date).isoformat()
    except UserError as e:
        r.err(str(e))
        return r
    c = check_json(r, d, paths)
    if c and check_output and isinstance(c.get("meta"), dict):
        try:
            check_html(r, c, d, paths)
        except Exception as e:
            r.err(f"出力HTMLの検証中に例外: {type(e).__name__}: {e}")
    return r


def print_report(r: Report, label: str = "") -> None:
    for i in r.infos:
        print(f"  INFO  {i}")
    for w in r.warns:
        print(f"  WARN  {w}")
    for e in r.errors:
        print(f"  ERROR {e}")
    print(f"\n[validate] {label + ' ' if label else ''}ERROR {len(r.errors)} / WARN {len(r.warns)}")


def main(date: str, paths: Paths = DEFAULT_PATHS) -> int:
    r = validate(date, paths)
    print_report(r, date)
    return 0 if r.ok else 1


if __name__ == "__main__":
    setup_stdio()
    if len(sys.argv) != 2:
        raise SystemExit("usage: python build/validate.py YYYY-MM-DD")
    sys.exit(main(sys.argv[1]))

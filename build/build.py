#!/usr/bin/env python3
"""
build.py — content/<DATE>.json から教材HTMLを組み立てる。

使い方:
    python build/build.py 2026-09-20      （通常は lesson.py build 経由）

設計方針:
  * 「中身（JSON）」と「見た目（templates/）」を完全に分離する。
    Claude Code は JSON だけを書けばよく、HTMLの構造ミスが原理的に起きない。
  * 本文は独自の軽量マークアップで書く（後述）。生HTMLを書かせない。
  * 会話全文（TTS用の hidden div）は turns から自動生成する。手書きしない。
  * 出力は一時ファイル経由で置き換える（途中で切れたHTMLを残さない）。改行は LF 固定。
  * 振り仮名：ハイライト語はツールチップの「語（よみ）」から自動で付ける。
    それ以外は本文に 箕面《みのお》市 / ｜SpeeCAN《スピーキャン》 と書く（青空文庫式）。
  * ビルドのたびに dist/index.html（教材一覧）も作り直す。
"""
from __future__ import annotations

import copy
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_PATHS, KANJI_RUN, TOKEN, Paths, UserError, align_reading, load_json,
    parse_date, render_ruby, ruby_tag, setup_stdio, strip_markup, write_text_atomic,
)

READ_CHARS_PER_MIN = 300  # 学習者が精読するときの目安

# ---------------------------------------------------------------- 軽量マークアップ
#   {{v:t1a|ヘクトパスカル}}  語彙ハイライト（黄）＋ツールチップ t1a を開く
#   {{g:t1e|〜にかけて}}      文法ハイライト（緑）＋ツールチップ t1e を開く
#   {{k:970}}                 キーワード強調（色付き太字）
#   {{b:重要}}                太字
#   {{br}}                    改行
#   箕面《みのお》市           振り仮名（どこでも使える）
# それ以外の文字はすべてHTMLエスケープされるので、生HTMLは混入しない。

# ツールチップ本文の先頭「<strong>語（よみ）</strong>」または「<strong>語</strong>（よみ）」
_TIP_HEAD = re.compile(
    r"<(?:strong|b)>\s*([^<（(]+?)\s*[（(]([^）)<]+)[）)]\s*</(?:strong|b)>"
    r"|<(?:strong|b)>\s*([^<（(]+?)\s*</(?:strong|b)>\s*[（(]([^）)<]+)[）)]"
)


def tooltip_reading(body: str) -> list[tuple[str, str]] | None:
    """ツールチップ本文の見出し語から、漢字ごとの読みを取り出す"""
    m = _TIP_HEAD.search(body or "")
    if not m:
        return None
    head, reading = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    return align_reading(head, reading)


_CARD_HEAD = re.compile(r"^\s*([^（(<]+?)\s*[（(]([ぁ-ゖァ-ヺー・]+)[）)]")


def _skeleton(head: str) -> str:
    """見出し語の「最後の漢字まで」（活用で変わる送り仮名を除いた部分）"""
    head = re.sub(r"[〜~\s]", "", head)
    runs = list(KANJI_RUN.finditer(head))
    if not runs:
        return ""
    return head[runs[0].start():runs[-1].end()]


def collect_readings(c: dict, gdict: dict) -> dict:
    """教材1つ分のツールチップ・語彙カードの「語（よみ）」を gdict に足す（既にある語は上書きしない）。

    キーは語の骨格（例：浮き彫りになる → 浮き彫）。漢字1字だけの骨格は
    読みが語によって変わる（上ヒゲ／上がる）ので入れない。
    """
    def add(head: str, reading: str) -> None:
        pairs = align_reading(head, reading)
        sk = _skeleton(head)
        if pairs and sum(len(k) for k, _ in pairs) >= 2 and sk not in gdict:
            gdict[sk] = pairs

    if not isinstance(c, dict):
        return gdict
    news = c.get("news") if isinstance(c.get("news"), dict) else {}
    arts = news.get("articles", []) if isinstance(news.get("articles"), list) else []
    for a in arts:
        for t in a.get("tooltips", []) if isinstance(a, dict) else []:
            m = _TIP_HEAD.search((t or {}).get("body", "") if isinstance(t, dict) else "")
            if m:
                add(*((m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))))
    cards = []
    for a in arts:
        if isinstance(a, dict) and isinstance(a.get("vocab_box"), dict):
            cards += a["vocab_box"].get("items", [])
    scene = c.get("scene") if isinstance(c.get("scene"), dict) else {}
    cards += scene.get("vocab", []) if isinstance(scene.get("vocab"), list) else []
    ext = c.get("ext") if isinstance(c.get("ext"), dict) else {}
    for s in ext.get("sections", []) if isinstance(ext.get("sections"), list) else []:
        if isinstance(s, dict) and s.get("type") == "cards":
            cards += s.get("items", [])
    for v in cards:
        m = _CARD_HEAD.match(v.get("jp", "")) if isinstance(v, dict) else None
        if m:
            add(m.group(1), m.group(2))
    return gdict


def saved_readings(paths: Paths = DEFAULT_PATHS) -> dict[str, list]:
    """data/readings.json：片付けた（削除した）教材から引き継いだ読み"""
    f = paths.data / "readings.json"
    if not f.exists():
        return {}
    try:
        entries = load_json(f).get("entries", {})
    except (UserError, AttributeError):
        return {}
    return {k: [tuple(x) for x in v] for k, v in entries.items() if isinstance(v, list)}


def reading_dictionary(paths: Paths = DEFAULT_PATHS, extra: dict | None = None) -> dict[str, list]:
    """振り仮名の辞書。優先順：その日の教材 → 新しい教材 → data/readings.json（片付けた教材の読み）"""
    gdict: dict[str, list] = {}
    if extra:
        collect_readings(extra, gdict)
    files = sorted(paths.content.glob("*.json"), reverse=True)
    saved = paths.data / "readings.json"
    key = (str(paths.content), tuple((f.name, f.stat().st_mtime_ns) for f in files),
           saved.stat().st_mtime_ns if saved.exists() else 0)
    if key not in _GDICT_CACHE:
        base: dict[str, list] = {}
        for f in files:
            try:
                collect_readings(load_json(f), base)
            except UserError:
                continue
        for k, v in saved_readings(paths).items():
            base.setdefault(k, v)
        _GDICT_CACHE.clear()
        _GDICT_CACHE[key] = base
    for k, v in _GDICT_CACHE[key].items():
        gdict.setdefault(k, v)
    return gdict


_GDICT_CACHE: dict = {}


def label_pairs(label: str, own: list | None, gdict: dict | None) -> tuple[list | None, str]:
    """ラベルに使う読みを決める → (pairs, 適用範囲)。範囲 "" はラベル全体"""
    if own:
        return own, ""
    for sk in sorted(gdict or {}, key=len, reverse=True):
        if sk in label:
            return gdict[sk], sk
    return None, ""


def ruby_label(label: str, pairs: list[tuple[str, str]] | None, scope: str = "") -> str:
    """ハイライト語のラベルに振り仮名を付ける（明示の《》があればそちらを優先）"""
    if "《" in label or not pairs:
        return render_ruby(label)
    if scope:  # 辞書の語はその語の部分だけに付ける
        i = label.find(scope)
        return (html.escape(label[:i]) + ruby_label(scope, pairs)
                + html.escape(label[i + len(scope):]))
    known = sorted(pairs, key=lambda p: -len(p[0]))
    out, pos = [], 0
    for m in KANJI_RUN.finditer(label):
        out.append(html.escape(label[pos:m.start()]))
        run, i = m.group(), 0
        while i < len(run):  # 漢字の連なりを、既知の語で左から貪欲に覆う
            hit = next(((k, r) for k, r in known if run.startswith(k, i)), None)
            if hit:
                out.append(ruby_tag(html.escape(hit[0]), html.escape(hit[1]), "rb-a"))
                i += len(hit[0])
            else:
                out.append(html.escape(run[i]))
                i += 1
        pos = m.end()
    out.append(html.escape(label[pos:]))
    return "".join(out)


def render_inline(text: str, auto: dict[str, list] | None = None, gdict: dict | None = None) -> str:
    """軽量マークアップ付きテキスト → HTML断片

    auto  … ツールチップID → その語の読み（ツールチップ本文から）
    gdict … 過去教材も含めた読みの辞書（auto に読みがないときに使う）
    """
    auto = auto or {}
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        out.append(render_ruby(text[pos:m.start()]))
        kind, a, b = m.group(1), m.group(2), m.group(3)
        if kind == "br":
            out.append("<br>")
        elif kind == "k":
            out.append(f'<span class="keyword">{render_ruby(a or "")}</span>')
        elif kind == "b":
            out.append(f"<strong>{render_ruby(a or '')}</strong>")
        elif kind in ("v", "g"):
            cls = "vocab-hl" if kind == "v" else "grammar-hl"
            tid = a or ""
            raw = b if b is not None else tid
            label = ruby_label(raw, *label_pairs(raw, auto.get(tid), gdict))
            # IDはJS文字列に直接埋め込まず data 属性経由で渡す（引用符が混ざっても壊れない）
            out.append(
                f'<span class="{cls}" role="button" tabindex="0" data-tip="{html.escape(tid)}"'
                f' onclick="showTooltip(this.dataset.tip,this)">{label}</span>'
            )
        pos = m.end()
    out.append(render_ruby(text[pos:]))
    return "".join(out)


def render_paragraphs(paras: list[str], auto: dict | None = None) -> str:
    return "<br><br>".join(render_inline(p, auto) for p in paras)


def article_auto(art: dict) -> dict[str, list]:
    auto = {}
    for t in art.get("tooltips", []) if isinstance(art.get("tooltips"), list) else []:
        if isinstance(t, dict):
            pairs = tooltip_reading(t.get("body", ""))
            if pairs:
                auto[t.get("id", "")] = pairs
    return auto


def missing_readings(art: dict, gdict: dict) -> list[str]:
    """振り仮名が付かない漢字を含むハイライト語（validate の INFO 用）"""
    auto, out = article_auto(art), []
    for p in art.get("paragraphs", []) if isinstance(art.get("paragraphs"), list) else []:
        if not isinstance(p, str):
            continue
        for m in TOKEN.finditer(p):
            if m.group(1) not in ("v", "g"):
                continue
            label = m.group(3) if m.group(3) is not None else (m.group(2) or "")
            kanji = sum(len(r) for r in KANJI_RUN.findall(strip_markup(label)))
            if not kanji:
                continue
            h = render_inline(m.group(0), auto, gdict)
            covered = sum(len("".join(KANJI_RUN.findall(b)))
                          for b in re.findall(r"<ruby[^>]*>(.*?)<rp>", h))
            if covered < kanji:
                out.append(label)
    return out


# ---------------------------------------------------------------- 生HTMLフィールドのルビ
# 本文・セリフ（エスケープして描画）と SVG 以外の文字列は、生HTMLとしてそのまま出力される。
# そこでもルビ記法だけは <ruby> に変換する。
_INLINE_FIELDS = re.compile(r"^news\.articles\[\d+\]\.paragraphs\[\d+\]$|^scene\.turns\[\d+\]\.jp$"
                            r"|^scene\.illustrations\[\d+\]\.svg$|^scene\.dialogue_full$|^meta\.")


def ruby_raw_fields(o, path: str = ""):
    if isinstance(o, dict):
        return {k: ruby_raw_fields(v, f"{path}.{k}" if path else k) for k, v in o.items()}
    if isinstance(o, list):
        return [ruby_raw_fields(v, f"{path}[{i}]") for i, v in enumerate(o)]
    if isinstance(o, str) and "《" in o and not _INLINE_FIELDS.match(path):
        return render_ruby(o, escape=False)
    return o


# ---------------------------------------------------------------- TTS用 会話全文
# 「」を外し、読点で区切って連結する。記号はTTSが誤読するので落とす。
_DROP = str.maketrans({c: None for c in "「」『』（）()…—－-＝=*※♪→⇔"})


def build_dialogue_full(turns: list[dict]) -> str:
    parts = []
    for t in turns:
        s = strip_markup(t.get("jp", ""), speech=True).translate(_DROP).strip()
        s = re.sub(r"\s+", "", s)
        if s:
            parts.append(s if s.endswith(("。", "？", "！")) else s + "。")
    return "".join(parts)


# ---------------------------------------------------------------- パレット
def load_palette(name: str, paths: Paths = DEFAULT_PATHS) -> dict:
    palettes = load_json(paths.data / "palettes.json")
    if name not in palettes:
        raise UserError(
            f"パレット '{name}' が data/palettes.json にありません。使えるのは: {', '.join(palettes)}"
        )
    return palettes[name]


def _field_of(art: dict) -> str:
    """目次に出す分野名。article.field があればそれ、なければ source の「/ 分野（」から拾う"""
    if art.get("field"):
        return str(art["field"])
    m = re.search(r"/\s*([^/（(]+?)\s*[（(]", art.get("source", ""))
    return m.group(1) if m else ""


# ---------------------------------------------------------------- 組み立て
def _env(paths: Paths):
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError:
        raise UserError("Jinja2 がインストールされていません。`lesson setup` を実行してください。")
    env = Environment(
        loader=FileSystemLoader(str(paths.templates)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # 断片は build.py 側でエスケープ済み
    )
    env.filters["inline"] = render_inline
    return env


def render(c: dict, paths: Paths = DEFAULT_PATHS) -> str:
    """content の dict → HTML文字列（ファイルには書かない）"""
    _env(paths)  # Jinja2 が無ければここで分かりやすいエラーにする
    from jinja2.exceptions import TemplateError, UndefinedError

    c = copy.deepcopy(c)  # 呼び出し側の dict を書き換えない
    try:
        meta = c["meta"]
        palette = load_palette(meta.get("palette", "indigo"), paths)

        # --- 会話全文（TTS用）はルビ変換の前に作る
        scene = c["scene"]
        full = scene.get("dialogue_full") or build_dialogue_full(scene["turns"])

        # --- ニュース本文：振り仮名つきで段落ごとに整形（ツールチップは変換前の本文から読みを拾う）
        gdict = reading_dictionary(paths, extra=c)
        for i, art in enumerate(c["news"]["articles"], 1):
            auto = article_auto(art)
            paras = art["paragraphs"]
            art["paras_html"] = [render_inline(p, auto, gdict) for p in paras]
            chars = len(strip_markup("".join(paras)))
            body = "".join(paras)
            art["stats"] = {
                "chars": chars,
                "minutes": max(1, round(chars / READ_CHARS_PER_MIN)),
                "highlights": sum(1 for m in TOKEN.finditer(body) if m.group(1) in ("v", "g")),
            }
            art["field"] = _field_of(art)
            art["anchor"] = f"art{i}"

        c = ruby_raw_fields(c)
        meta, scene = c["meta"], c["scene"]
        scene["dialogue_full"] = html.escape(full, quote=False)

        env = _env(paths)
        css = env.get_template("styles.css.j2").render(p=palette, speakers=scene.get("speaker_colors", {}))
        js = (paths.templates / "app.js").read_text(encoding="utf-8")

        return env.get_template("base.html.j2").render(
            meta=meta, news=c["news"], scene=scene, ext=c["ext"],
            p=palette, css=css, js=js,
        )
    except (KeyError, TypeError, AttributeError, UndefinedError) as e:
        raise UserError(
            f"JSONの構造が不足・不正なためHTMLを組み立てられません（{type(e).__name__}: {e}）。"
            " `lesson validate <日付>` で原因箇所を確認してください。"
        )
    except TemplateError as e:
        raise UserError(f"テンプレートのエラー: {e}")


# ---------------------------------------------------------------- 教材一覧
def build_index(paths: Paths = DEFAULT_PATHS) -> Path | None:
    """dist/index.html：ビルド済みの全教材を新しい順に並べた一覧"""
    tpl = paths.templates / "index.html.j2"
    if not tpl.exists():
        return None
    items = []
    for f in sorted(paths.content.glob("*.json"), reverse=True):
        try:
            c = load_json(f)
            meta = c["meta"]
            out = paths.dist_file(meta["date_jp"])
        except (UserError, KeyError, TypeError):
            continue
        if not out.exists():
            continue
        palette = {}
        try:
            palette = load_palette(meta.get("palette", ""), paths)
        except UserError:
            pass
        arts = c.get("news", {}).get("articles", []) if isinstance(c.get("news"), dict) else []
        items.append({
            "date": meta.get("date", f.stem), "date_jp": meta["date_jp"], "weekday": meta.get("weekday", ""),
            "emoji": meta.get("theme_emoji", "🗣️"),
            "theme": strip_markup(str(meta.get("theme_label", ""))),
            "href": quote(out.name),
            "color": (palette.get("gradient") or ["#4338ca"])[0],
            "titles": [strip_markup(str(a.get("title", ""))) for a in arts if isinstance(a, dict)],
        })
    html_out = _env(paths).get_template("index.html.j2").render(items=items)
    out = paths.dist / "index.html"
    write_text_atomic(out, html_out)
    write_text_atomic(paths.dist / "latest.html", latest_redirect(items[0] if items else None))
    return out


def latest_redirect(item: dict | None) -> str:
    """dist/latest.html：いつ開いても最新の教材へ飛ぶページ（ブックマーク・公開サイト用）"""
    href = item["href"] if item else "index.html"
    label = f"{item['date_jp']}（{item['weekday']}）{item['emoji']} {item['theme']}" if item else "教材一覧"
    return (
        "<!DOCTYPE html>\n<html lang=\"ja\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1.0\">"
        f"<meta http-equiv=\"refresh\" content=\"0; url={href}\"><title>最新の教材へ</title>"
        "<style>body{font-family:sans-serif;background:#111827;color:#f9fafb;padding:2rem}a{color:#fde68a}</style>"
        f"</head><body><p>最新の教材に移動します… <a href=\"{href}\">{html.escape(label)}</a></p>"
        "<p><a href=\"index.html\">教材一覧</a></p>"
        f"<script>location.replace({json.dumps(href)});</script></body></html>\n"
    )


def main(date: str, paths: Paths = DEFAULT_PATHS, quiet: bool = False) -> Path:
    d = parse_date(date).isoformat()
    src = paths.content_file(d)
    if not src.exists():
        raise UserError(f"{src} がありません。先に `lesson new {d}` を実行してください。")

    c = load_json(src)
    html_out = render(c, paths)

    out = paths.dist_file(c["meta"]["date_jp"])
    write_text_atomic(out, html_out)
    build_index(paths)
    if not quiet:
        kb = len(html_out.encode("utf-8")) / 1024
        print(f"[build] OK  {out}  ({kb:.1f} KB)")
    return out


if __name__ == "__main__":
    setup_stdio()
    if len(sys.argv) != 2:
        raise SystemExit("usage: python build/build.py YYYY-MM-DD")
    try:
        main(sys.argv[1])
    except UserError as e:
        raise SystemExit(f"[build] ERROR {e}")

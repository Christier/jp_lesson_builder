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
"""
from __future__ import annotations

import copy
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_PATHS, TOKEN, Paths, UserError, load_json, parse_date, setup_stdio,
    strip_markup, write_text_atomic,
)

# ---------------------------------------------------------------- 軽量マークアップ
#   {{v:t1a|ヘクトパスカル}}  語彙ハイライト（黄）＋ツールチップ t1a を開く
#   {{g:t1e|〜にかけて}}      文法ハイライト（緑）＋ツールチップ t1e を開く
#   {{k:970}}                 キーワード強調（色付き太字）
#   {{b:重要}}                太字
#   {{br}}                    改行
# それ以外の文字はすべてHTMLエスケープされるので、生HTMLは混入しない。


def render_inline(text: str) -> str:
    """軽量マークアップ付きテキスト → HTML断片"""
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        kind, a, b = m.group(1), m.group(2), m.group(3)
        if kind == "br":
            out.append("<br>")
        elif kind == "k":
            out.append(f'<span class="keyword">{html.escape(a or "")}</span>')
        elif kind == "b":
            out.append(f"<strong>{html.escape(a or '')}</strong>")
        elif kind in ("v", "g"):
            cls = "vocab-hl" if kind == "v" else "grammar-hl"
            label = html.escape(b if b is not None else (a or ""))
            tid = html.escape(a or "")
            # IDはJS文字列に直接埋め込まず data 属性経由で渡す（引用符が混ざっても壊れない）
            out.append(
                f'<span class="{cls}" data-tip="{tid}" onclick="showTooltip(this.dataset.tip)">{label}</span>'
            )
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def render_paragraphs(paras: list[str]) -> str:
    return "<br><br>".join(render_inline(p) for p in paras)


# ---------------------------------------------------------------- TTS用 会話全文
# 「」を外し、読点で区切って連結する。記号はTTSが誤読するので落とす。
_DROP = str.maketrans({c: None for c in "「」『』（）()…—－-＝=*※♪→⇔"})


def build_dialogue_full(turns: list[dict]) -> str:
    parts = []
    for t in turns:
        s = strip_markup(t.get("jp", "")).translate(_DROP).strip()
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


# ---------------------------------------------------------------- 組み立て
def render(c: dict, paths: Paths = DEFAULT_PATHS) -> str:
    """content の dict → HTML文字列（ファイルには書かない）"""
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
        from jinja2.exceptions import TemplateError, UndefinedError
    except ImportError:
        raise UserError("Jinja2 がインストールされていません。`lesson setup` を実行してください。")

    c = copy.deepcopy(c)  # 呼び出し側の dict を書き換えない
    try:
        meta = c["meta"]
        palette = load_palette(meta.get("palette", "indigo"), paths)

        # --- ニュース本文を整形
        for art in c["news"]["articles"]:
            art["body_html"] = render_paragraphs(art["paragraphs"])

        # --- 会話全文を自動生成（手書きされていればそれを優先）
        scene = c["scene"]
        full = scene.get("dialogue_full") or build_dialogue_full(scene["turns"])
        scene["dialogue_full"] = html.escape(full, quote=False)

        speaker_colors = scene.get("speaker_colors", {})

        env = Environment(
            loader=FileSystemLoader(str(paths.templates)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False,  # 断片は build.py 側でエスケープ済み
        )
        env.filters["inline"] = render_inline

        css = env.get_template("styles.css.j2").render(p=palette, speakers=speaker_colors)
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


def main(date: str, paths: Paths = DEFAULT_PATHS, quiet: bool = False) -> Path:
    d = parse_date(date).isoformat()
    src = paths.content_file(d)
    if not src.exists():
        raise UserError(f"{src} がありません。先に `lesson new {d}` を実行してください。")

    c = load_json(src)
    html_out = render(c, paths)

    out = paths.dist_file(c["meta"]["date_jp"])
    write_text_atomic(out, html_out)
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

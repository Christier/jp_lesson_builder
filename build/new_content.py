#!/usr/bin/env python3
"""
new_content.py — 当日分の content/<DATE>.json の雛形を作る。

使い方:
    python build/new_content.py 2026-09-20      （通常は lesson.py new 経由）

・配色は「一番長く使っていないもの」を自動で選ぶ（未使用があればそれを優先）
・和暦表記（date_jp）と曜日を自動計算する
・ニュース3本分の枠（ツールチップIDは t1a / t2a / t3a 系）を最初から用意する
・中身はプレースホルダー。残っていると validate が ERROR を出す。
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_PATHS, Paths, UserError, date_jp, load_json, parse_date, setup_stdio,
    weekday_jp, write_json,
)

# 雛形に残っていたら「書き忘れ」とみなす文字列（validate が参照する）
PLACEHOLDERS = (
    "（会話テーマを書く）", "（実際に参照した媒体名）", "分野1", "分野2", "分野3",
    "媒体名 / 分野", "見出し——サブ見出し", "キーワード：・・・", "本文1段落目", "本文2段落目",
    "中文释义。", "（タイトル）", "（状況説明", "（今日の会話で", "場面：・・・", "登場人物：・・・",
    "（分野）の重要語彙", "（日本語のセリフ）", "（中文訳）", "（解説）", "（ロールプレイ課題",
    "（中国語メモ→", "列1", "<b>【例】</b><br>本文", "ステップ1（5分）</strong>：…",
    "（見出し）", "（質問）", "（答え）", "（語彙）", "（中文）", "（転用例）", "（会話テーマの短い名前）",
)


def _article(n: int) -> dict:
    return {
        "source": "📡 媒体名 / 分野（発表時刻）",
        "title": "見出し——サブ見出し",
        "date_line": "YYYY年M月D日 | キーワード：・・・",
        "gradient": None,
        "paragraphs": [
            f"本文1段落目。{{{{v:t{n}a|語彙}}}}や{{{{g:t{n}b|文法}}}}をマークアップで指定し、{{{{k:数値}}}}は強調する。",
            "本文2段落目。",
        ],
        "tooltips": [
            {"id": f"t{n}a", "body": "📌 <strong>語彙（読み）</strong>：中文释义。用法・搭配・派生。"},
            {"id": f"t{n}b", "body": "🔤 <strong>文法：〜</strong>：中文释义。例文と、過去教材との復習リンク。"},
        ],
        "vocab_box": {
            "title": f"📖 ニュース{n} 重要単語まとめ（分野・仕事に転用）",
            "items": [{"jp": "（語彙）", "cn": "（中文）", "ex": "（転用例）"}],
        },
    }


SKELETON = {
    "meta": {
        "date": "", "date_jp": "", "weekday": "",
        "theme_emoji": "🗣️",
        "theme_label": "（会話テーマを書く）",
        "palette": "",
        "study_minutes": 120,
        "level": "N1",
        "sources": "（実際に参照した媒体名）",
        "tabs": {"news": "📰 今日のニュース", "scene": "🗣️ 場面会話", "ext": "🧩 拡張学習"},
        "badges": [
            {"color": "red", "text": "🔴 本日のニュース3本（分野1・分野2・分野3）"},
            {"color": "green", "text": "🗣️ 場面会話18ターン"},
            {"color": "blue", "text": "🔊 音声読み上げ対応"},
            {"color": "amber", "text": "🧩 拡張学習・クイズ付き"},
        ],
    },
    "news": {
        "heading": "📰 YYYY年M月D日 — 本日の主要ニュース（分野1／分野2／分野3）",
        "audio_note": "🎙️ 真人音声は <a href=\"https://www3.nhk.or.jp/news/easy/\" target=\"_blank\">NHK NEWS WEB EASY</a>／<a href=\"https://www.nhk.or.jp/radionews/\" target=\"_blank\">NHKラジオニュース</a> で。下の🔊はブラウザTTS（意味確認・シャドーイング用）です。",
        "articles": [_article(1), _article(2), _article(3)],
        "headlines": [{"time": "", "jp": "（見出し）", "cn": "（中文）"}],
    },
    "scene": {
        "title": "🗣️ 場面会話：（タイトル）",
        "intro": "（状況説明。今日のニュースとどう繋がるかを書く）",
        "aim": "（今日の会話で身につける技術を1〜2文で）",
        "tts_hint": "▶ シャドーイングは0.85xがおすすめ",
        "dialogue_title": "📍 場面：・・・ | 登場人物：・・・",
        "speaker_colors": {"a": "#3730a3", "you": "#c2410c"},
        "illustrations": [],
        "vocab_heading": "（分野）の重要語彙",
        "vocab": [{"jp": "（語彙）", "cn": "（中文）", "note": "（転用例）"}],
        "turns": [
            {"section": "🔹 セクション名", "speaker": "a", "speaker_label": "相手",
             "jp": "「（日本語のセリフ）」", "cn": "（中文訳）", "note": "🔤 （解説）"},
            {"side": "right", "speaker": "you", "speaker_label": "あなた",
             "jp": "「（日本語のセリフ）」", "cn": "（中文訳）", "note": "🔤 （解説）"},
        ],
        "dialogue_full": "",
        "roleplay": "（ロールプレイ課題。①〜⑦の手順と、使いたい表現リスト）",
    },
    "ext": {
        "sections": [
            {"type": "table", "heading": "🔁 拡張①：カジュアル ⇔ フォーマル（タイトル）", "lead": "",
             "headers": ["列1", "列2", "列3"], "rows": [["", "", ""]]},
            {"type": "info", "heading": "📨 拡張②：（タイトル）", "cards": ["<b>【例】</b><br>本文"]},
            {"type": "cards", "heading": "📖 拡張③：（タイトル）",
             "items": [{"jp": "（語彙）", "cn": "（中文）", "note": "（転用例）"}]},
            {"type": "note", "heading": "🎧 拡張④：シャドーイング練習法",
             "body": "<strong>ステップ1（5分）</strong>：…<br><strong>ステップ2（10分）</strong>：…"},
        ],
        "quiz": [{"q": "（質問）", "a": "（答え）"}],
        "challenge": "（中国語メモ→日本語への通訳課題。最後は「できたら見せてください、添削します！」で締める）",
    },
    # lesson record がこれを読んで data/themes.json と data/vocab-index.json を更新する
    "index": {
        "theme": "（会話テーマの短い名前）",
        "terms": [],
    },
}


def pick_palette(paths: Paths = DEFAULT_PATHS, exclude_date: str | None = None) -> str:
    """未使用の配色を優先し、なければ最後に使った日が一番古いものを返す。"""
    palettes = list(load_json(paths.data / "palettes.json"))
    used = load_json(paths.data / "themes.json").get("used", [])
    last_used: dict[str, str] = {}
    for u in used:
        if u.get("date") == exclude_date or u.get("palette") not in palettes:
            continue
        last_used[u["palette"]] = max(last_used.get(u["palette"], ""), u.get("date", ""))
    # 未使用 → "" で最優先。同順位は palettes.json の並び順。
    return min(palettes, key=lambda p: (last_used.get(p, ""), palettes.index(p)))


def make_skeleton(date: str, paths: Paths = DEFAULT_PATHS) -> dict:
    d = parse_date(date)
    sk = copy.deepcopy(SKELETON)
    ymd = date_jp(d)
    sk["meta"]["date"] = d.isoformat()
    sk["meta"]["date_jp"] = ymd
    sk["meta"]["weekday"] = weekday_jp(d)
    sk["meta"]["palette"] = pick_palette(paths, exclude_date=d.isoformat())
    sk["news"]["heading"] = f"📰 {ymd} — 本日の主要ニュース（分野1／分野2／分野3）"
    for a in sk["news"]["articles"]:
        a["date_line"] = f"{ymd} | キーワード：・・・"
    return sk


def main(date: str | None, paths: Paths = DEFAULT_PATHS) -> Path:
    d = parse_date(date).isoformat()
    out = paths.content_file(d)
    if out.exists():
        raise UserError(f"{out} は既にあります。上書きしたくないので中止します。")

    sk = make_skeleton(d, paths)
    write_json(out, sk)
    print(f"[new] {out} を作成（配色: {sk['meta']['palette']}）")
    print("[new] 次: ニュースを調べて articles 3本・scene・ext・index を埋める")
    return out


if __name__ == "__main__":
    setup_stdio()
    if len(sys.argv) > 2:
        raise SystemExit("usage: python build/new_content.py [YYYY-MM-DD]")
    try:
        main(sys.argv[1] if len(sys.argv) == 2 else None)
    except UserError as e:
        raise SystemExit(f"[new] ERROR {e}")

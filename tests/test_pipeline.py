"""
jp-lesson-builder の自動テスト（標準ライブラリ unittest のみ）。

    lesson test        または   python -m unittest discover tests

本物の content/ data/ dist/ は一切書き換えない。毎回一時ディレクトリに
プロジェクトの複製を作り、その中でビルド・検証・記録を行う。

  * templates/・data/palettes.json・content/2026-09-19.json … 本物をコピー
  * data/themes.json・data/vocab-index.json … tests/fixtures/data/ の固定版をコピー
    （9/19 教材まで記録済みの時点で凍結。日々の lesson record で本物の data/ が
      育っても、テストの期待値は変わらない）
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import date as Date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "build"))

import build  # noqa: E402
import new_content  # noqa: E402
import record  # noqa: E402
import review  # noqa: E402
import validate  # noqa: E402
from common import Paths, UserError, load_json, strip_markup  # noqa: E402

SAMPLE = "2026-09-19"


class ProjectCase(unittest.TestCase):
    """一時ディレクトリにプロジェクトの複製を作る"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jlb-test-"))
        shutil.copytree(ROOT / "templates", self.tmp / "templates")
        for sub in ("data", "content", "dist"):
            (self.tmp / sub).mkdir()
        shutil.copy2(ROOT / "data" / "palettes.json", self.tmp / "data")
        for name in ("themes.json", "vocab-index.json"):
            shutil.copy2(FIXTURES / "data" / name, self.tmp / "data")
        shutil.copy2(ROOT / "content" / f"{SAMPLE}.json", self.tmp / "content")
        self.paths = Paths(self.tmp)
        self._quiet = contextlib.redirect_stdout(io.StringIO())  # [new] [record] などの出力を抑える
        self._quiet.__enter__()

    def tearDown(self) -> None:
        self._quiet.__exit__(None, None, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- helpers
    def sample(self) -> dict:
        return load_json(self.paths.content_file(SAMPLE))

    def save(self, c: dict, date: str = SAMPLE) -> None:
        self.paths.content_file(date).write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")

    def run_validate(self, c: dict | None = None, date: str = SAMPLE, build_first: bool = True):
        if c is not None:
            self.save(c, date)
        if build_first:
            try:
                build.main(date, self.paths, quiet=True)
            except UserError:
                pass
        return validate.validate(date, self.paths)

    def assertHas(self, msgs: list[str], needle: str) -> None:
        self.assertTrue(any(needle in m for m in msgs), f"'{needle}' が見つからない: {msgs}")


# ====================================================================== マークアップ
class TestMarkup(unittest.TestCase):
    def test_render_inline_escapes_raw_html(self):
        out = build.render_inline("A<script>x</script>&B")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("&amp;B", out)

    def test_render_inline_tokens(self):
        out = build.render_inline("{{v:t1a|語}}{{g:t1b|文法}}{{k:970}}{{b:重要}}{{br}}")
        self.assertIn('class="vocab-hl" role="button" tabindex="0" data-tip="t1a"', out)
        self.assertIn('class="grammar-hl" role="button" tabindex="0" data-tip="t1b"', out)
        self.assertIn('<span class="keyword">970</span>', out)
        self.assertIn("<strong>重要</strong>", out)
        self.assertIn("<br>", out)

    def test_tooltip_id_cannot_break_out_of_attribute(self):
        out = build.render_inline("{{v:a\"onmouseover=\"x|語}}")
        self.assertNotIn('"onmouseover="', out)

    def test_strip_markup(self):
        self.assertEqual(strip_markup("中心{{v:t1a|気圧}}は{{k:975}}<b>hPa</b>{{br}}"), "中心気圧は975hPa")

    def test_dialogue_full(self):
        s = build.build_dialogue_full([{"jp": "「はい、{{b:承知}}しました」"}, {"jp": "本当ですか？"}, {"jp": ""}])
        self.assertEqual(s, "はい、承知しました。本当ですか？")


# ====================================================================== build
class TestBuild(ProjectCase):
    def test_build_sample(self):
        out = build.main(SAMPLE, self.paths, quiet=True)
        raw = out.read_bytes()
        self.assertNotIn(b"\r\n", raw, "改行は LF 固定")
        s = raw.decode("utf-8")
        self.assertTrue(s.rstrip().endswith("</html>"))
        for tab in ("tab-news", "tab-scene", "tab-ext", "dialogue-full"):
            self.assertIn(f'id="{tab}"', s)
        self.assertEqual(out.name, "N1日语学习-2026年9月19日.html")

    def test_build_is_deterministic(self):
        a = build.main(SAMPLE, self.paths, quiet=True).read_bytes()
        b = build.main(SAMPLE, self.paths, quiet=True).read_bytes()
        self.assertEqual(a, b)

    def test_render_does_not_mutate_input(self):
        c = self.sample()
        before = copy.deepcopy(c)
        build.render(c, self.paths)
        self.assertEqual(c, before)

    def test_missing_content_is_user_error(self):
        with self.assertRaises(UserError):
            build.main("2030-01-01", self.paths, quiet=True)

    def test_broken_structure_is_user_error_not_traceback(self):
        c = self.sample()
        del c["scene"]["turns"]
        self.save(c)
        with self.assertRaises(UserError):
            build.main(SAMPLE, self.paths, quiet=True)

    def test_unknown_palette(self):
        c = self.sample()
        c["meta"]["palette"] = "nope"
        self.save(c)
        with self.assertRaises(UserError):
            build.main(SAMPLE, self.paths, quiet=True)


# ====================================================================== validate
class TestValidate(ProjectCase):
    def test_sample_has_no_errors(self):
        r = self.run_validate()
        self.assertEqual(r.errors, [])

    def mutate(self, fn) -> validate.Report:
        c = self.sample()
        fn(c)
        return self.run_validate(c)

    def test_missing_tooltip(self):
        r = self.mutate(lambda c: c["news"]["articles"][0]["tooltips"].pop(0))
        self.assertHas(r.errors, "未定義")

    def test_orphan_tooltip(self):
        r = self.mutate(lambda c: c["news"]["articles"][0]["tooltips"].append({"id": "t1zz", "body": "x"}))
        self.assertHas(r.errors, "参照されていない")

    def test_duplicate_tooltip_id(self):
        def f(c):
            a1, a2 = c["news"]["articles"][0], c["news"]["articles"][1]
            a2["tooltips"].append({"id": a1["tooltips"][0]["id"], "body": "x"})
            a2["paragraphs"].append(f"{{{{v:{a1['tooltips'][0]['id']}|重複}}}}")
        self.assertHas(self.mutate(f).errors, "重複")

    def test_bad_tooltip_id(self):
        def f(c):
            c["news"]["articles"][0]["tooltips"].append({"id": "t'1", "body": "x"})
            c["news"]["articles"][0]["paragraphs"].append("{{v:t'1|語}}")
        self.assertHas(self.mutate(f).errors, "使えない文字")

    def test_unclosed_markup(self):
        r = self.mutate(lambda c: c["news"]["articles"][0]["paragraphs"].append("{{v:t1a|閉じてない"))
        self.assertHas(r.errors, "閉じていない")

    def test_vg_token_in_turn(self):
        def f(c):
            c["scene"]["turns"][0]["jp"] += "{{v:t1a|語}}"
        self.assertHas(self.mutate(f).errors, "セリフでは")

    def test_placeholder_left(self):
        r = self.mutate(lambda c: c["news"]["articles"][0].update(title="見出し——サブ見出し"))
        self.assertHas(r.errors, "プレースホルダー")

    def test_broken_svg(self):
        r = self.mutate(lambda c: c["scene"]["illustrations"][0].update(svg="<svg viewBox='0 0 1 1'><rect></svg>"))
        self.assertHas(r.errors, "SVGが整形式ではありません")

    def test_unbalanced_html(self):
        r = self.mutate(lambda c: c["news"]["articles"][0]["tooltips"][0].update(body="<strong>閉じない"))
        self.assertHas(r.errors, "閉じられていません")

    def test_event_handler_attr(self):
        r = self.mutate(lambda c: c["ext"].update(challenge='<b onclick="x()">添削</b>'))
        self.assertHas(r.errors, "スクリプト")

    def test_date_jp_and_weekday(self):
        r = self.mutate(lambda c: c["meta"].update(date_jp="2026年9月20日", weekday="日"))
        self.assertHas(r.errors, "meta.date_jp")
        self.assertHas(r.errors, "meta.weekday")

    def test_bad_gradient(self):
        r = self.mutate(lambda c: c["news"]["articles"][1].update(gradient=["#000"]))
        self.assertHas(r.errors, "gradient")

    def test_unknown_section_type(self):
        r = self.mutate(lambda c: c["ext"]["sections"].append({"type": "video", "heading": "x"}))
        self.assertHas(r.errors, "未対応")

    def test_too_few_quiz_and_turns(self):
        def f(c):
            c["ext"]["quiz"] = c["ext"]["quiz"][:7]
            c["scene"]["turns"] = c["scene"]["turns"][:15]
        r = self.mutate(f)
        self.assertHas(r.errors, "クイズが7問")
        self.assertHas(r.errors, "15ターン")

    def test_badge_mismatch_is_warning(self):
        r = self.mutate(lambda c: c["meta"]["badges"][1].update(text="🗣️ 場面会話18ターン"))
        self.assertEqual(r.errors, [])
        self.assertHas(r.warns, "18ターン")

    def test_stale_html(self):
        build.main(SAMPLE, self.paths, quiet=True)
        src = self.paths.content_file(SAMPLE)
        future = time.time() + 10
        os.utime(src, (future, future))
        r = validate.validate(SAMPLE, self.paths)
        self.assertHas(r.errors, "JSONがHTMLより新しく")

    def test_garbage_never_raises(self):
        variants = [
            lambda c: c["news"].update(articles="x"),
            lambda c: c["news"].update(articles=[1, None]),
            lambda c: c["news"]["articles"][0].update(tooltips=[None, 3]),
            lambda c: c["scene"].update(turns=[1, 2]),
            lambda c: c["scene"].update(speaker_colors=None),
            lambda c: c["ext"].update(sections=None, quiz="x"),
            lambda c: c.update(index=[1]),
            lambda c: c["meta"].update(badges="x", tabs=None),
            lambda c: c.update(meta=None),
        ]
        original = self.sample()
        for n, fn in enumerate(variants):
            with self.subTest(variant=n):
                c = copy.deepcopy(original)
                fn(c)
                self.save(c)
                r = validate.validate(SAMPLE, self.paths)  # 例外が出ないこと
                self.assertFalse(r.ok)

    def test_broken_json(self):
        self.paths.content_file(SAMPLE).write_text("{ broken", encoding="utf-8")
        r = validate.validate(SAMPLE, self.paths)
        self.assertHas(r.errors, "JSONが壊れています")

    def test_bad_date(self):
        r = validate.validate("2026/9/19", self.paths)
        self.assertHas(r.errors, "YYYY-MM-DD")


# ====================================================================== new
class TestNew(ProjectCase):
    def test_new_creates_skeleton(self):
        out = new_content.main("2026-09-20", self.paths)
        c = load_json(out)
        self.assertEqual(c["meta"]["date_jp"], "2026年9月20日")
        self.assertEqual(c["meta"]["weekday"], "日")
        self.assertEqual(len(c["news"]["articles"]), 3)
        self.assertEqual(c["meta"]["palette"], "teal")  # 一番長く使っていない配色
        self.assertNotIn(b"\r\n", out.read_bytes())

    def test_new_refuses_overwrite(self):
        with self.assertRaises(UserError):
            new_content.main(SAMPLE, self.paths)

    def test_skeleton_builds_but_fails_validation(self):
        new_content.main("2026-09-20", self.paths)
        r = self.run_validate(None, "2026-09-20")
        self.assertHas(r.errors, "プレースホルダー")
        self.assertHas(r.errors, "クイズ")

    def test_pick_palette_prefers_unused(self):
        t = load_json(self.paths.data / "themes.json")
        t["used"] = [u for u in t["used"] if u["palette"] != "sky"]
        (self.paths.data / "themes.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(new_content.pick_palette(self.paths), "sky")

    def test_bad_date(self):
        with self.assertRaises(UserError):
            new_content.main("2026-13-01", self.paths)


# ====================================================================== record
class TestRecord(ProjectCase):
    def data_bytes(self):
        return {n: (self.paths.data / n).read_bytes() for n in ("themes.json", "vocab-index.json")}

    def test_sample_record_is_noop(self):
        before = self.data_bytes()
        build.main(SAMPLE, self.paths, quiet=True)
        self.assertEqual(record.main(SAMPLE, self.paths), 0)
        self.assertEqual(self.data_bytes(), before)

    def test_compact_format_roundtrip(self):
        for n in ("themes.json", "vocab-index.json"):
            p = self.paths.data / n
            self.assertEqual(record.dumps_compact(load_json(p)), p.read_text(encoding="utf-8"))

    def test_plan_adds_and_is_idempotent(self):
        themes = load_json(self.paths.data / "themes.json")
        vindex = load_json(self.paths.data / "vocab-index.json")
        cand = themes["candidates"][0]
        c = {"meta": {"palette": "teal", "theme_label": "x"},
             "index": {"theme": cand, "terms": [{"term": "あいにく", "kind": "adverb"},
                                                {"term": "新語テスト", "kind": "vocab"}]}}
        t1, v1, _ = record.plan(c, "2026-10-01", themes, vindex)
        self.assertEqual(t1["used"][-1], {"date": "2026-10-01", "theme": cand, "palette": "teal"})
        self.assertNotIn(cand, t1["candidates"])
        terms = {e["term"]: e for e in v1["entries"]}
        self.assertEqual(terms["新語テスト"]["first"], "2026-10-01")
        self.assertIn("2026-10-01", terms["あいにく"]["seen"])
        self.assertEqual(terms["あいにく"]["first"], "2026-09-19")
        t2, v2, _ = record.plan(c, "2026-10-01", t1, v1)
        self.assertEqual((t1, v1), (t2, v2))

    def test_prune(self):
        themes = load_json(self.paths.data / "themes.json")
        vindex = load_json(self.paths.data / "vocab-index.json")
        c = {"meta": {"palette": "autumn", "theme_label": "x"}, "index": {"theme": "x", "terms": []}}
        _, v, log = record.plan(c, SAMPLE, themes, vindex, prune=False)
        self.assertEqual(v, vindex)
        _, v, _ = record.plan(c, SAMPLE, themes, vindex, prune=True)
        self.assertFalse(any(SAMPLE in e["seen"] for e in v["entries"]))
        self.assertNotIn("あいにく", {e["term"] for e in v["entries"]})  # 9/19 だけの語は消える

    def test_refuses_when_validation_fails(self):
        c = self.sample()
        c["ext"]["quiz"] = []
        self.save(c)
        build.main(SAMPLE, self.paths, quiet=True)
        before = self.data_bytes()
        self.assertEqual(record.main(SAMPLE, self.paths), 1)
        self.assertEqual(self.data_bytes(), before)


# ====================================================================== 本物の教材
class TestRealContent(unittest.TestCase):
    """本物の content/*.json が、現行テンプレートで ERROR 0 のままビルドできること（回帰確認）"""

    def test_all_lessons_build_without_errors(self):
        tmp = Path(tempfile.mkdtemp(prefix="jlb-real-"))
        try:
            for d in ("data", "templates", "content"):
                shutil.copytree(ROOT / d, tmp / d)
            paths = Paths(tmp)
            files = sorted(paths.content.glob("*.json"))
            self.assertTrue(files)
            with contextlib.redirect_stdout(io.StringIO()):
                for f in files:
                    with self.subTest(lesson=f.stem):
                        build.main(f.stem, paths, quiet=True)
                        self.assertEqual(validate.validate(f.stem, paths).errors, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ====================================================================== review
class TestReview(ProjectCase):
    def test_categories(self):
        r = review.collect(self.paths, Date(2026, 10, 10))
        fixed = {x["term"] for x in r["fixed"]}
        once = {x["term"] for x in r["once"]}
        self.assertIn("こまめに", fixed)
        self.assertIn("あいにく", once)
        self.assertEqual(r["missing"], [])
        md = review.to_markdown(r, Date(2026, 10, 10))
        self.assertIn("定着候補", md)


if __name__ == "__main__":
    unittest.main()

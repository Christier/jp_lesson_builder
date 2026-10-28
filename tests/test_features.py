"""
振り仮名・下書きの結合・夜間実行・タスク登録のテスト。

夜間実行は本物の Claude Code を起動しない。CLAUDE_BIN に偽の claude（tests 内で作る
小さな Python スクリプト）を指定し、「何もしない」「教材を完成させる」「未ログイン」を再現する。
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import time
import unittest
from datetime import date as Date_, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402
import clean  # noqa: E402
import drafts  # noqa: E402
import nightly  # noqa: E402
import schedule  # noqa: E402
import validate  # noqa: E402
from common import UserError, align_reading, load_json, render_ruby, strip_markup  # noqa: E402
from test_pipeline import ROOT, SAMPLE, ProjectCase  # noqa: E402


# ====================================================================== 振り仮名
class TestFurigana(unittest.TestCase):
    def test_align_reading(self):
        cases = {
            ("浮き彫りになる", "うきぼりになる"): [("浮", "う"), ("彫", "ぼ")],
            ("〜を果たす", "はたす"): [("果", "は")],
            ("不正アクセス", "ふせいアクセス"): [("不正", "ふせい")],
            ("ハッシュ値", "ハッシュち"): [("値", "ち")],
            ("後手に回る", "ごてにまわる"): [("後手", "ごて"), ("回", "まわ")],
            ("〜うる／〜える", "得る"): None,       # 読みにかな以外
            ("ひらがな", "ひらがな"): None,          # 漢字がない
        }
        for (head, reading), want in cases.items():
            with self.subTest(head=head):
                self.assertEqual(align_reading(head, reading), want)

    def test_render_ruby_and_escape(self):
        h = render_ruby("大阪府｜箕面《みのお》市の<b>")
        self.assertIn('<ruby class="rb-x">箕面<rp>（</rp><rt>みのお</rt><rp>）</rp></ruby>市', h)
        self.assertIn("大阪府", h)
        self.assertIn("&lt;b&gt;", h)

    def test_strip_markup_speech(self):
        s = "{{v:t1a|膨《ふく》らみ}}、大阪府｜箕面《みのお》市"
        self.assertEqual(strip_markup(s), "膨らみ、大阪府箕面市")
        self.assertEqual(strip_markup(s, speech=True), "ふくらみ、大阪府みのお市")

    def test_auto_ruby_from_tooltip(self):
        auto = {"t1a": build.tooltip_reading("📌 <strong>膨らむ（ふくらむ）</strong>：膨胀")}
        h = build.render_inline("注文が{{v:t1a|膨らみ}}、", auto)
        self.assertIn('<ruby class="rb-a">膨<rp>（</rp><rt>ふく</rt><rp>）</rp></ruby>らみ', h)
        self.assertIn('role="button" tabindex="0" data-tip="t1a"', h)

    def test_explicit_ruby_in_label_wins(self):
        auto = {"t1a": [("大幅", "だいはば")]}
        h = build.render_inline("{{v:t1a|大幅《おおはば》}}", auto)
        self.assertIn("<rt>おおはば</rt>", h)
        self.assertNotIn("だいはば", h)

    def test_dictionary_only_whole_words(self):
        gdict = {"浮き彫": [("浮", "う"), ("彫", "ぼ")]}
        pairs, scope = build.label_pairs("課題が浮き彫りになった", None, gdict)
        h = build.ruby_label("課題が浮き彫りになった", pairs, scope)
        self.assertIn("<rt>う</rt>", h)
        self.assertNotIn("課<rp>", h)  # 辞書の語以外の漢字には付けない


class TestFuriganaPipeline(ProjectCase):
    def test_ruby_in_raw_fields_and_paragraph_markup(self):
        c = self.sample()
        c["news"]["articles"][0]["tooltips"][0]["body"] += "（父島《ちちじま》）"
        c["news"]["articles"][0]["paragraphs"][0] = "父島《ちちじま》の" + c["news"]["articles"][0]["paragraphs"][0]
        self.save(c)
        html_out = build.main(SAMPLE, self.paths, quiet=True).read_text(encoding="utf-8")
        self.assertIn('<p class="np">', html_out)
        self.assertIn('<ruby class="rb-x">父島<rp>（</rp><rt>ちちじま</rt>', html_out)
        self.assertNotIn("《", html_out.split("<script>")[0].split('id="dialogue-full"')[0])

    def test_index_page(self):
        build.main(SAMPLE, self.paths, quiet=True)
        idx = (self.paths.dist / "index.html").read_text(encoding="utf-8")
        self.assertIn("N1%E6%97%A5%E8%AF%AD", idx)  # 日本語ファイル名は URL エンコード
        self.assertIn("最新", idx)
        latest = (self.paths.dist / "latest.html").read_text(encoding="utf-8")
        self.assertIn('url=N1%E6%97%A5%E8%AF%AD', latest)  # いちばん新しい教材へ飛ぶ
        self.assertIn("location.replace", latest)

    def test_cross_lesson_dictionary(self):
        prev = self.sample()
        prev["meta"].update(date="2026-09-01", date_jp="2026年9月1日", weekday="火")
        prev["news"]["articles"][0]["tooltips"][0]["body"] = "📌 <strong>見極める（みきわめる）</strong>：看清"
        self.save(prev, "2026-09-01")
        c = self.sample()
        c["news"]["articles"][0]["paragraphs"][0] += "{{v:t1a|見極めて}}"
        tip = c["news"]["articles"][0]["tooltips"][0]
        tip["body"] = "📌 見極める：看清（読みなし）"
        g = build.reading_dictionary(self.paths, extra=c)
        self.assertEqual(g["見極"], [("見極", "みきわ")])

    def test_validate_ruby_errors(self):
        c = self.sample()
        p = c["news"]["articles"][0]["paragraphs"]
        p[0] = "大阪府箕面《みのお》市" + p[0]          # 親文字が長すぎる → WARN
        p[1] = "東京《とうきょう" + p[1]               # 閉じていない → ERROR
        c["scene"]["turns"][0]["note"] += "漢字《かんji》"  # かな以外 → WARN
        r = self.run_validate(c)
        self.assertHas(r.warns, "親文字『大阪府箕面』が長すぎる")
        self.assertHas(r.errors, "振り仮名の記法が不正")
        self.assertHas(r.warns, "かな以外")

    def test_validate_reports_missing_readings(self):
        c = self.sample()
        a = c["news"]["articles"][0]
        a["tooltips"].append({"id": "t1zz", "body": "📌 読みのない解説"})
        a["paragraphs"][0] += "{{v:t1zz|難読語彙}}"
        r = self.run_validate(c)
        self.assertEqual(r.errors, [])
        self.assertHas(r.infos, "難読語彙")


# ====================================================================== 下書きの結合
class TestMerge(ProjectCase):
    def write(self, name: str, obj) -> Path:
        d = self.paths.drafts / SAMPLE
        d.mkdir(parents=True, exist_ok=True)
        p = d / name
        p.write_text(json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj, encoding="utf-8")
        return p

    def test_merge_parts(self):
        self.write("news.json", {"heading": "新しい見出し"})               # キーなし → news とみなす
        self.write("scene.json", {"scene": {"title": "新しい場面"}})
        self.write("x_index.json", {"index": {"theme": "テスト", "terms": []}})
        drafts.main(SAMPLE, None, self.paths)
        c = load_json(self.paths.content_file(SAMPLE))
        self.assertEqual(c["news"]["heading"], "新しい見出し")
        self.assertTrue(c["news"]["articles"])          # 浅い上書きなので他のキーは残る
        self.assertEqual(c["scene"]["title"], "新しい場面")
        self.assertTrue(c["scene"]["turns"])
        self.assertEqual(c["index"]["theme"], "テスト")

    def test_merge_errors(self):
        self.write("bad.json", "{ broken")
        with self.assertRaises(UserError):
            drafts.main(SAMPLE, None, self.paths)
        (self.paths.drafts / SAMPLE / "bad.json").unlink()
        self.write("odd.json", {"other": 1})
        with self.assertRaises(UserError):
            drafts.main(SAMPLE, None, self.paths)
        with self.assertRaises(UserError):
            drafts.main("2030-01-01", None, self.paths)


# ====================================================================== 夜間実行
FAKE_CLAUDE = r'''
import json, os, shutil, sys, pathlib
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "noop")
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": mode != "logout"}))
    sys.exit(0)
prompt = sys.stdin.read()
log = pathlib.Path(os.environ["FAKE_LOG"])
with log.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"args": args, "prompt": prompt}, ensure_ascii=False) + "\n")
MSGS = {  # 最初の N 回は、実際に起きたエラーを返す
    "transient": "Failed to refresh OAuth token: another Claude Code process is refreshing it or exited mid-refresh.",
    "limit": "You've hit your weekly limit · resets 6pm (Asia/Tokyo)",   # 2026-10-23 の再現
}
prefix = next((p for p in MSGS if mode.startswith(p)), None)
if prefix:
    n = int(mode[len(prefix):] or 1)
    cnt = pathlib.Path(str(log) + ".count")
    k = int(cnt.read_text()) if cnt.exists() else 0
    cnt.write_text(str(k + 1))
    if k < n:
        msg = MSGS[prefix]
        print(json.dumps({"type": "assistant", "is_api_error_message": True,
                          "message": {"content": [{"type": "text", "text": msg}]}}))
        print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "num_turns": 1,
                          "terminal_reason": "api_error", "result": msg, "total_cost_usd": 0}))
        sys.exit(1)
    mode = "complete"
if mode == "complete":
    sys.path.insert(0, os.environ["FAKE_BUILD"])
    from common import Paths
    import build, record
    root = pathlib.Path.cwd()
    date = os.environ["FAKE_DATE"]
    c = json.loads((root / "content" / "2026-09-19.json").read_text(encoding="utf-8"))
    c["meta"].update(date=date, date_jp="2026年9月20日", weekday="日", palette="teal")
    c["index"] = {"theme": "偽のテーマ", "terms": [{"term": "偽語", "kind": "vocab"}]}
    (root / "content" / f"{date}.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    build.main(date, Paths(root), quiet=True)
    record.main(date, Paths(root))
print(json.dumps({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Bash", "input": {"command": "./lesson.sh check"}}]}}))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
                  "result": "報告です", "total_cost_usd": 0.01}))
'''


class TestNightly(ProjectCase):
    DATE = "2026-09-20"

    def setUp(self):
        super().setUp()
        fake_py = self.tmp / "fake_claude.py"
        fake_py.write_text(FAKE_CLAUDE, encoding="utf-8")
        if os.name == "nt":
            fake = self.tmp / "fake_claude.cmd"
            fake.write_text(f'@"{sys.executable}" "{fake_py}" %*\r\n', encoding="utf-8")
        else:
            fake = self.tmp / "fake_claude.sh"
            fake.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake_py}" "$@"\n', encoding="utf-8")
            fake.chmod(0o755)
        self.calls = self.tmp / "calls.jsonl"
        self.env = {"CLAUDE_BIN": str(fake), "FAKE_LOG": str(self.calls), "FAKE_DATE": self.DATE,
                    "FAKE_BUILD": str(ROOT / "build"), "PYTHONUTF8": "1"}
        self.old_env = {k: os.environ.get(k) for k in [*self.env, "FAKE_MODE"]}
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def run_nightly(self, mode: str, date: str | None = None, **kw) -> int:
        os.environ["FAKE_MODE"] = mode
        return nightly.main(date or self.DATE, self.paths, notify_=False, **kw)

    def latest(self) -> dict:
        return json.loads((self.paths.logs / "latest.json").read_text(encoding="utf-8"))

    def calls_made(self) -> list[dict]:
        if not self.calls.exists():
            return []
        return [json.loads(l) for l in self.calls.read_text(encoding="utf-8").splitlines()]

    def test_target_date(self):
        self.assertEqual(nightly.target_date(None, datetime(2026, 10, 17, 22, 0)), "2026-10-17")
        self.assertEqual(nightly.target_date(None, datetime(2026, 10, 18, 8, 0)), "2026-10-17")  # 取りこぼし分
        self.assertEqual(nightly.target_date("2026-10-01"), "2026-10-01")

    def test_skip_when_complete(self):
        self.assertEqual(self.run_nightly("noop", SAMPLE), 0)
        self.assertEqual(self.latest()["status"], "skipped")
        self.assertEqual(self.calls_made(), [])

    def test_dry_run_does_not_call_claude(self):
        self.assertEqual(self.run_nightly("noop", dry_run=True), 0)
        self.assertEqual(self.calls_made(), [])
        self.assertIn("dry-run", self.latest()["message"])

    def test_incomplete_retries_then_fails(self):
        self.assertEqual(self.run_nightly("noop", retries=1), 1)
        calls = self.calls_made()
        self.assertEqual(len(calls), 2)
        self.assertIn("--allowedTools", calls[0]["args"])
        self.assertIn("Bash(./lesson.sh:*)", calls[0]["args"])
        self.assertIn("無人の定時実行", calls[0]["prompt"])
        self.assertIn("【続きから】", calls[1]["prompt"])
        j = self.latest()
        self.assertEqual(j["status"], "failed")
        self.assertEqual(len(j["runs"]), 2)
        self.assertFalse((self.paths.logs / "nightly.lock").exists())

    def test_complete_run_succeeds(self):
        self.assertEqual(self.run_nightly("complete", retries=0), 0)
        j = self.latest()
        self.assertEqual(j["status"], "success")
        self.assertTrue(j["html"].endswith("2026年9月20日.html"))
        themes = load_json(self.paths.data / "themes.json")
        self.assertEqual(themes["used"][-1]["date"], self.DATE)
        log = (self.paths.logs / f"{self.DATE}-nightly.log").read_text(encoding="utf-8")
        self.assertIn("→ Bash: ./lesson.sh check", log)
        self.assertIn("報告です", log)

    def test_not_logged_in(self):
        self.assertEqual(self.run_nightly("logout"), 1)
        self.assertIn("lesson.cmd login", self.latest()["message"])
        self.assertEqual(self.calls_made(), [])

    def no_wait(self):
        waits = []
        old = nightly.SLEEP
        nightly.SLEEP = waits.append
        self.addCleanup(setattr, nightly, "SLEEP", old)
        return waits

    def test_transient_error_backs_off_then_succeeds(self):
        waits = self.no_wait()
        self.assertEqual(self.run_nightly("transient2", retries=0), 0)
        j = self.latest()
        self.assertEqual(j["status"], "success")
        self.assertEqual(len(j["runs"]), 3)
        self.assertIn("OAuth", j["runs"][0]["transient"])
        self.assertEqual(j["runs"][2]["transient"], "")
        self.assertEqual(waits, nightly.BACKOFF_SEC[:2])  # 間隔をあけて再試行（即時ではない）
        log = (self.paths.logs / f"{self.DATE}-nightly.log").read_text(encoding="utf-8")
        self.assertIn("一時的なエラー", log)

    def test_transient_error_does_not_use_content_retries(self):
        self.no_wait()
        self.assertEqual(self.run_nightly("transient1", retries=0), 0)  # retries=0 でも完成まで行く
        self.assertEqual(self.latest()["status"], "success")

    def test_transient_error_forever(self):
        waits = self.no_wait()
        self.assertEqual(self.run_nightly("transient99", retries=1), 1)
        j = self.latest()
        self.assertEqual(len(j["runs"]), len(nightly.BACKOFF_SEC) + 1)
        self.assertEqual(waits, nightly.BACKOFF_SEC)
        self.assertIn("一時的なエラーが続きました", j["message"])
        self.assertIn("login --force", j["message"])

    def test_stale_refresh_lock(self):
        home = self.tmp / "home"
        lock = home / ".claude" / ".oauth_refresh.lock"
        lock.mkdir(parents=True)
        old = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
        os.environ["USERPROFILE"] = os.environ["HOME"] = str(home)
        try:
            log = nightly.Logger(self.paths.logs / "t.log")
            nightly.clear_stale_refresh_lock(log)
            self.assertTrue(lock.exists())  # 新しいロックは外さない（更新中かもしれない）
            t = time.time() - 30 * 60
            os.utime(lock, (t, t))
            (lock / "x").write_text("busy", encoding="utf-8")
            nightly.clear_stale_refresh_lock(log)
            self.assertTrue(lock.exists())  # 空でなければ触らない
            (lock / "x").unlink()
            os.utime(lock, (t, t))
            nightly.clear_stale_refresh_lock(log)
            self.assertFalse(lock.exists())  # 古くて空 → 取り残しなので外す
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_commit_and_push(self):
        import subprocess
        def git(*a, cwd=self.tmp):
            return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True,
                                  encoding="utf-8").stdout.strip()
        remote = self.tmp.parent / (self.tmp.name + "-remote.git")
        self.addCleanup(lambda: __import__("shutil").rmtree(remote, ignore_errors=True))
        git("init", "--bare", "-b", "main", str(remote), cwd=self.tmp.parent)
        git("init", "-b", "main")
        git("config", "user.name", "test"); git("config", "user.email", "test@example.com")
        git("add", "content", "data"); git("commit", "-m", "init")
        git("remote", "add", "origin", str(remote))
        git("push", "origin", "main")
        self.assertEqual(self.run_nightly("complete", retries=0, push=True), 0)
        msg = git("log", "-1", "--format=%s", "main", cwd=remote)
        self.assertIn(f"lesson: {self.DATE}", msg)  # リモートに届いている
        files = git("show", "--name-only", "--format=", "main", cwd=remote).splitlines()
        self.assertEqual(sorted(files), sorted([f"content/{self.DATE}.json", "data/themes.json",
                                                "data/vocab-index.json"]))  # 当日分だけ
        self.assertIn("GitHub に反映", self.latest()["message"])

    def test_push_with_clean_commits_deletions(self):
        import subprocess
        def git(*a, cwd=self.tmp):
            return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True,
                                  encoding="utf-8").stdout.strip()
        remote = self.tmp.parent / (self.tmp.name + "-remote.git")
        self.addCleanup(lambda: __import__("shutil").rmtree(remote, ignore_errors=True))
        git("init", "--bare", "-b", "main", str(remote), cwd=self.tmp.parent)
        git("init", "-b", "main")
        git("config", "user.name", "test"); git("config", "user.email", "test@example.com")
        git("add", "content", "data"); git("commit", "-m", "init")
        git("remote", "add", "origin", str(remote))
        git("push", "origin", "main")
        # 今日から見て 9/19 も 9/20 も古いが、いちばん新しい 9/20 は必ず残る
        self.assertEqual(self.run_nightly("complete", retries=0, push=True, keep_days=3), 0)
        status = git("show", "--name-status", "--format=%s", "main", cwd=remote).splitlines()
        self.assertIn("整理", status[0])
        self.assertIn(f"A\tcontent/{self.DATE}.json", status)
        self.assertIn(f"D\tcontent/{SAMPLE}.json", status)       # 片付けた教材の削除も push される
        self.assertIn("A\tdata/readings.json", status)           # 消した教材の読みは引き継ぐ
        self.assertFalse(self.paths.content_file(SAMPLE).exists())

    def test_usage_limit_parse(self):
        now = datetime(2026, 10, 23, 22, 2)
        self.assertEqual(nightly.usage_limit({"text": "You've hit your weekly limit · resets 6pm (Asia/Tokyo)"}, now),
                         ("weekly", datetime(2026, 10, 24, 18, 0)))
        self.assertEqual(nightly.usage_limit({"text": "You've hit your session limit · resets 12:50am"}, now),
                         ("session", datetime(2026, 10, 24, 0, 50)))
        self.assertIsNone(nightly.usage_limit({"text": "Failed to refresh OAuth token"}, now))

    def test_usage_limit_far_reset_stops_immediately(self):
        waits = self.no_wait()
        old = nightly.LIMIT_WAIT_MAX
        nightly.LIMIT_WAIT_MAX = 0  # リセットが遠い（2026-10-23 は翌日18時）
        self.addCleanup(setattr, nightly, "LIMIT_WAIT_MAX", old)
        self.assertEqual(self.run_nightly("limit99", retries=1), 1)
        j = self.latest()
        self.assertEqual(len(j["runs"]), 1)        # 10分おきの無駄な再試行をしない
        self.assertEqual(waits, [])
        self.assertIn("利用上限（weekly）", j["message"])
        self.assertNotIn("login", j["message"])    # ログインの問題ではない

    def test_usage_limit_near_reset_waits_then_succeeds(self):
        waits = self.no_wait()
        old = nightly.LIMIT_WAIT_MAX
        nightly.LIMIT_WAIT_MAX = 10 ** 9
        self.addCleanup(setattr, nightly, "LIMIT_WAIT_MAX", old)
        self.assertEqual(self.run_nightly("limit1", retries=0), 0)
        self.assertEqual(len(waits), 1)
        self.assertGreater(waits[0], 0)
        self.assertEqual(self.latest()["status"], "success")

    def test_lock_prevents_double_run(self):
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        (self.paths.logs / "nightly.lock").write_text("pid=1", encoding="utf-8")
        self.assertEqual(self.run_nightly("noop"), 1)
        self.assertIn("実行中", self.latest()["message"])


# ====================================================================== 片付け
class TestClean(ProjectCase):
    TODAY = Date_(2026, 10, 28)

    def make(self, days_ago: int, tip: str = "") -> str:
        d = self.TODAY - timedelta(days=days_ago)
        c = json.loads(json.dumps(self.base))
        c["meta"].update(date=d.isoformat(), date_jp=f"{d.year}年{d.month}月{d.day}日",
                         weekday="月火水木金土日"[d.weekday()])
        if tip:
            c["news"]["articles"][0]["tooltips"][0]["body"] = tip
        self.save(c, d.isoformat())
        build.main(d.isoformat(), self.paths, quiet=True)
        (self.paths.drafts / d.isoformat()).mkdir(parents=True, exist_ok=True)
        (self.paths.drafts / d.isoformat() / "news.json").write_text("{}", encoding="utf-8")
        self.paths.logs.mkdir(exist_ok=True)
        (self.paths.logs / f"{d.isoformat()}-claude.jsonl").write_text("x" * 1000, encoding="utf-8")
        return d.isoformat()

    def setUp(self):
        super().setUp()
        self.base = self.sample()
        self.paths.content_file(SAMPLE).unlink()  # 9/19 のサンプルそのものは使わない
        self.dates = [self.make(n) for n in (0, 1, 2, 3, 5)]

    def remaining(self):
        return sorted(f.stem for f in self.paths.content.glob("*.json"))

    def test_keeps_three_days(self):
        r = clean.main(3, self.paths, today=self.TODAY, log=lambda *_: None)
        self.assertEqual(self.remaining(), sorted(self.dates[:3]))
        self.assertEqual(sorted(r["content"]), sorted(f"content/{d}.json" for d in self.dates[3:]))
        html = sorted(f.name for f in self.paths.dist.glob("N1*.html"))
        self.assertEqual(len(html), 3)
        self.assertEqual(sorted(d.name for d in self.paths.drafts.iterdir()), sorted(self.dates[:3]))
        self.assertEqual(len(list(self.paths.logs.glob("*-claude.jsonl"))), 3)
        idx = (self.paths.dist / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("10/23", idx)  # 一覧も作り直される

    def test_dry_run_deletes_nothing(self):
        before = self.remaining()
        r = clean.main(3, self.paths, today=self.TODAY, dry_run=True, log=lambda *_: None)
        self.assertEqual(self.remaining(), before)
        self.assertEqual(r["count"], 0)

    def test_newest_is_always_kept(self):
        clean.main(1, self.paths, today=self.TODAY + timedelta(days=30), log=lambda *_: None)
        self.assertEqual(self.remaining(), [self.dates[0]])

    def test_readings_survive_deletion(self):
        old = self.make(10, tip="📌 <strong>見極める（みきわめる）</strong>：看清")
        clean.main(3, self.paths, today=self.TODAY, log=lambda *_: None)
        self.assertFalse(self.paths.content_file(old).exists())
        saved = load_json(self.paths.data / "readings.json")["entries"]
        self.assertEqual(saved["見極"], [["見極", "みきわ"]])
        self.assertEqual(build.reading_dictionary(self.paths)["見極"], [("見極", "みきわ")])

    def test_invalid_keep_days(self):
        with self.assertRaises(UserError):
            clean.main(0, self.paths, today=self.TODAY, log=lambda *_: None)


# ====================================================================== タスク登録
class TestSchedule(unittest.TestCase):
    def test_install_script(self):
        from common import Paths
        s = schedule.install_script(Paths(Path(r"C:\work\it's lesson")), "22:00", ["--commit"], wake=False)
        self.assertIn("-Daily -At '22:00'", s)
        self.assertIn("-StartWhenAvailable", s)
        self.assertIn("-MultipleInstances IgnoreNew", s)
        self.assertIn("-LogonType Interactive", s)
        self.assertNotIn("-WakeToRun", s)
        self.assertIn("-Execute 'conhost.exe'", s)  # 既定は窓なし
        self.assertIn("--headless cmd.exe /c", s)
        self.assertIn("it''s lesson", s)  # パス中の ' は PowerShell リテラルで '' になる
        self.assertIn('nightly.cmd" --commit"', s)
        exe, arg = schedule.task_action(Paths(Path(r"C:\my work\jlb")), [], visible=True)
        self.assertEqual(exe, "cmd.exe")
        self.assertEqual(arg, '/c ""' + str(Path(r"C:\my work\jlb") / "nightly.cmd") + '""')

    def test_bad_time(self):
        from common import Paths
        with self.assertRaises(UserError):
            schedule.install_script(Paths(ROOT), "25:00", [], wake=False)


if __name__ == "__main__":
    unittest.main()

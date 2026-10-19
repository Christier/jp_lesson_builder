#!/usr/bin/env python3
"""
nightly.py — 毎晩の自動生成（無人実行）。タスクスケジューラから nightly.cmd 経由で呼ばれる。

    lesson nightly [DATE] [--force] [--commit] [--no-notify] [--retries N] [--dry-run]
    lesson nightly --smoke      Claude Code を非対話で起動できるかだけ確かめる（教材は作らない）

流れ:
  1. 対象日を決める。省略時は「正午より前なら前日、正午以降なら当日」
     （22時の実行を取りこぼし、翌朝PCを起動したときに走った場合でも前日分を作るため）
  2. 既に完成していれば何もしない（validate ERROR 0 かつ data/themes.json に記録済み）
  3. Claude Code（claude -p）を非対話で起動し、.claude/commands/lesson.md の手順で作らせる
  4. 終わったら自分で build → validate し直し、記録も確認する（Claude の自己申告を信用しない）。
     未完成なら「続きから」でもう一度起動する（--retries、既定1回）
  5. 結果を logs/ に残し、Windows ならトースト通知を出す。--commit なら当日分だけ git commit

環境変数:
  CLAUDE_BIN              claude の実行ファイル（既定：PATH → ~/.local/bin/claude(.exe) → npm）
  LESSON_NIGHTLY_MODEL    使うモデル（既定：Claude Code の既定）
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DEFAULT_PATHS, Paths, UserError, load_json, parse_date, write_text_atomic  # noqa: E402

MAX_TURNS = 200
TIMEOUT_MIN = 120

# 無人実行で Claude に許す操作。Bash は教材ツールと読み取り系だけ。
ALLOWED_TOOLS = [
    "Bash(./lesson.sh:*)", "Bash(date:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(wc:*)",
    "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite",
]
DISALLOWED_TOOLS = ["Bash(rm:*)", "Bash(git push:*)", "Bash(git reset:*)", "Bash(git checkout:*)"]


# ---------------------------------------------------------------- 準備
def target_date(arg: str | None, now: datetime | None = None) -> str:
    if arg:
        return parse_date(arg).isoformat()
    now = now or datetime.now()
    d = now.date() if now.hour >= 12 else now.date() - timedelta(days=1)
    return d.isoformat()


def find_claude() -> str | None:
    env = os.environ.get("CLAUDE_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for c in (home / ".local/bin/claude.exe", home / ".local/bin/claude",
              Path(os.environ.get("APPDATA", "")) / "npm/claude.cmd"):
        if c.exists():
            return str(c)
    return None


LOGIN_HELP = r"Claude Code（CLI）にログインしていません。PowerShell で `.\lesson.cmd login` を一度実行してください"


def claude_logged_in(claude: str) -> bool | None:
    """`claude auth status` で確認。判定できなければ None（その場合は起動して確かめる）"""
    try:
        r = subprocess.run([claude, "auth", "status"], capture_output=True, timeout=60)
        j = json.loads(r.stdout.decode("utf-8", errors="replace"))
        return bool(j.get("loggedIn"))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return None


def claude_cmd(claude: str, max_turns: int = MAX_TURNS) -> list[str]:
    cmd = [claude, "-p", "--output-format", "stream-json", "--verbose",
           "--permission-mode", "acceptEdits", "--max-turns", str(max_turns)]
    model = os.environ.get("LESSON_NIGHTLY_MODEL")
    if model:
        cmd += ["--model", model]
    return cmd + ["--allowedTools", *ALLOWED_TOOLS, "--disallowedTools", *DISALLOWED_TOOLS]


def make_prompt(date: str, resume: str | None = None) -> str:
    lines = [
        "これは無人の定時実行です。ユーザーは不在で、質問には答えられません。途中で確認を求めず、最後まで自分で判断して進めてください。",
        f"`.claude/commands/lesson.md` の手順（STEP 1〜6）と CLAUDE.md のルールに従って、{date} の教材を完成させてください。",
        "",
        "守ること:",
        "- 会話テーマは data/themes.json の候補・その日のニュース・季節から自分で選ぶ",
        f"- 本文は drafts/{date}/ に news.json・scene.json・ext.json と分けて Write し、`./lesson.sh merge {date}` で結合する（1回の書き込みで全部を書かない）",
        f"- `./lesson.sh check {date}` の ERROR が 0 になるまで直し、最後に `./lesson.sh record {date}` まで実行する",
        "- Bash で使ってよいのは ./lesson.sh だけ（python を直接呼ばない）",
        "- 最後に、ニュース3本の要旨（数値と出典）・会話テーマ・生成ファイルのパスを日本語で簡潔に報告する",
    ]
    if resume:
        lines += ["", "【続きから】前回の実行は完成しませんでした。content と drafts の現状を確認し、続きから完成させてください。",
                  "前回の検証結果:", resume]
    return "\n".join(lines)


# ---------------------------------------------------------------- 状態の確認
def lesson_status(date: str, paths: Paths) -> dict:
    """教材の完成度。build し直してから validate する"""
    import build
    import validate
    st = {"exists": paths.content_file(date).exists(), "built": False, "ok": False,
          "recorded": False, "errors": [], "html": "", "theme": ""}
    if not st["exists"]:
        return st
    try:
        out = build.main(date, paths, quiet=True)
        st["built"], st["html"] = True, str(out)
    except UserError as e:
        st["errors"].append(f"build: {e}")
    r = validate.validate(date, paths)
    st["ok"] = r.ok and st["built"]
    st["errors"] += r.errors
    try:
        themes = load_json(paths.data / "themes.json")
        hit = [u for u in themes.get("used", []) if isinstance(u, dict) and u.get("date") == date]
        st["recorded"] = bool(hit)
        st["theme"] = hit[0].get("theme", "") if hit else ""
    except UserError as e:
        st["errors"].append(str(e))
    return st


def complete(st: dict) -> bool:
    return st["ok"] and st["recorded"]


# ---------------------------------------------------------------- 実行
class Logger:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(line, flush=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


@contextmanager
def single_run(lock: Path, stale_after_min: int = TIMEOUT_MIN * 2 + 30):
    """同時に2つ走らないようにする（古いロックは自動で外す）"""
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists() and time.time() - lock.stat().st_mtime > stale_after_min * 60:
        lock.unlink(missing_ok=True)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise UserError(f"別の nightly が実行中です（{lock}）。止まっている場合はこのファイルを消してください")
    try:
        os.write(fd, f"pid={os.getpid()} start={datetime.now().isoformat()}\n".encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def _describe(tool: dict) -> str:
    name, inp = tool.get("name", "?"), tool.get("input") or {}
    detail = inp.get("command") or inp.get("query") or inp.get("url") or inp.get("file_path") or inp.get("pattern") or ""
    return f"{name}: {str(detail)[:110]}"


def run_claude(cmd: list[str], prompt: str, cwd: Path, raw_log: Path, log: Logger,
               timeout_min: int = TIMEOUT_MIN) -> dict:
    """claude -p を起動し、stream-json を記録しながら進捗を表示する"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    killed = {"timeout": False}

    def on_timeout():
        killed["timeout"] = True
        proc.kill()

    timer = threading.Timer(timeout_min * 60, on_timeout)
    timer.start()
    result: dict = {}
    tools = 0
    api_error = False
    try:
        assert proc.stdin and proc.stdout
        proc.stdin.write(prompt.encode("utf-8"))
        proc.stdin.close()
        with raw_log.open("ab") as raw:
            for line in proc.stdout:
                raw.write(line)
                raw.flush()
                try:
                    ev = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    text = line.decode("utf-8", errors="replace").strip()
                    if text:
                        log(f"  | {text[:200]}")
                    continue
                if ev.get("type") == "assistant":
                    api_error |= bool(ev.get("is_api_error_message"))
                    for part in (ev.get("message") or {}).get("content", []) or []:
                        if isinstance(part, dict) and part.get("type") == "tool_use":
                            tools += 1
                            log(f"  → {_describe(part)}")
                elif ev.get("type") == "result":
                    result = ev
        proc.wait()
    finally:
        timer.cancel()
    return {
        "exit": proc.returncode, "timeout": killed["timeout"],
        "is_error": bool(result.get("is_error", True)) if result else True,
        "subtype": result.get("subtype", ""), "turns": result.get("num_turns"),
        "cost_usd": result.get("total_cost_usd"), "text": result.get("result", ""),
        "terminal_reason": result.get("terminal_reason", ""), "api_error": api_error, "tools": tools,
        "minutes": round((time.time() - t0) / 60, 1),
    }


# ---------------------------------------------------------------- 一時的なエラー
# 認証トークンの更新競合・混雑・レート制限など、待てば直るもの。教材の中身とは無関係なので
# 「続きから」の再実行回数とは別に、間隔をあけて再試行する。
BACKOFF_SEC = [60, 120, 300, 600]
SLEEP = time.sleep  # テストで差し替える
_TRANSIENT = re.compile(r"OAuth|refresh|token|overloaded|rate.?limit|429|5\d\d|timed? ?out|ECONN|network|"
                        r"temporar|Service Unavailable|過負荷|一時的", re.I)
STALE_LOCK_MIN = 10


def transient_error(s: dict) -> str:
    """一時的なエラーなら理由（短い文字列）、そうでなければ空文字"""
    text = (s.get("text") or "").strip()
    if s.get("timeout"):
        return ""
    if s.get("terminal_reason") == "api_error" or s.get("api_error"):
        return text[:80] or "APIエラー"
    if s.get("is_error") and not s.get("tools") and _TRANSIENT.search(text):
        return text[:80]
    return ""


def clear_stale_refresh_lock(log: Logger) -> None:
    """途中で落ちたプロセスが残したトークン更新ロック（空ディレクトリ）を外す。

    更新は数秒で終わるので、10分以上前のロックが残っていれば取り残しと判断できる。
    2026-10-17 22:00 の実行では、このロックが残って更新が全部失敗した。
    """
    lock = Path.home() / ".claude" / ".oauth_refresh.lock"
    try:
        age_min = (time.time() - lock.stat().st_mtime) / 60
    except OSError:
        return
    if age_min < STALE_LOCK_MIN:
        return
    try:
        if lock.is_dir():
            lock.rmdir()  # 空でなければ OSError で何もしない
        else:
            lock.unlink()
        log(f"[nightly] {age_min:.0f}分前から残っていたトークン更新ロックを外しました（{lock}）")
    except OSError as e:
        log(f"[nightly] トークン更新ロックを外せませんでした（{e}）")


# ---------------------------------------------------------------- 通知・コミット
def _ps_encoded(script: str) -> list[str]:
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc]


def _xml(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def notify(title: str, body: str, open_path: str = "") -> bool:
    """Windows のトースト通知（クリックでファイルを開く）。失敗しても処理は続ける"""
    if not sys.platform.startswith("win"):
        return False
    launch = Path(open_path).as_uri() if open_path else ""
    toast = (f'<toast activationType="protocol" launch="{_xml(launch)}">' if launch else "<toast>") + (
        f'<visual><binding template="ToastGeneric"><text>{_xml(title)}</text><text>{_xml(body)}</text>'
        "</binding></visual></toast>")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('{toast.replace(chr(39), chr(39) * 2)}');"
        "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
        "[Windows.UI.Notifications.ToastNotification]::new($x))"
    )
    try:
        r = subprocess.run(_ps_encoded(script), capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def git_commit(date: str, theme: str, paths: Paths, log: Logger) -> None:
    root = paths.root
    if not (root / ".git").exists():
        log("git: リポジトリではないのでコミットしません")
        return
    files = [f"content/{date}.json", "data/themes.json", "data/vocab-index.json"]
    try:
        subprocess.run(["git", "add", "--", *files], cwd=root, check=True, capture_output=True)
        msg = f"lesson: {date} {theme}（夜間自動生成）"
        r = subprocess.run(["git", "commit", "-m", msg, "--", *files], cwd=root, capture_output=True)
        out = (r.stdout + r.stderr).decode("utf-8", errors="replace").strip().splitlines()
        log(f"git: {'コミットしました' if r.returncode == 0 else 'コミットしませんでした'}（{out[0] if out else ''}）")
    except (OSError, subprocess.CalledProcessError) as e:
        log(f"git: 失敗（{e}）")


# ---------------------------------------------------------------- 本体
def smoke(paths: Paths = DEFAULT_PATHS) -> int:
    """claude を非対話で起動し、許可したコマンド（./lesson.sh doctor）を実行できるか確かめる"""
    claude = find_claude()
    if not claude:
        print("[smoke] NG  claude が見つかりません（Claude Code をインストールするか CLAUDE_BIN を設定）")
        return 1
    print(f"[smoke] claude: {claude}")
    if claude_logged_in(claude) is False:
        print(f"[smoke] NG  {LOGIN_HELP}")
        return 1
    paths.logs.mkdir(parents=True, exist_ok=True)
    log = Logger(paths.logs / "smoke.log")
    prompt = ("動作確認です。Bash で `./lesson.sh doctor` を実行し、出力の最後の行だけをそのまま答えてください。"
              "それ以外のことはしないでください。")
    s = run_claude(claude_cmd(claude, max_turns=4), prompt, paths.root, paths.logs / "smoke-claude.jsonl", log,
                   timeout_min=5)
    ok = not s["is_error"] and "問題なし" in (s["text"] or "")
    log(f"[smoke] {'OK' if ok else 'NG'}  {s['minutes']}分  turns={s['turns']}  応答: {(s['text'] or '').strip()[:120]}")
    return 0 if ok else 1


def main(date: str | None = None, paths: Paths = DEFAULT_PATHS, force: bool = False, commit: bool = False,
         notify_: bool = True, retries: int = 1, dry_run: bool = False) -> int:
    d = target_date(date)
    paths.logs.mkdir(parents=True, exist_ok=True)
    log = Logger(paths.logs / f"{d}-nightly.log")
    started = datetime.now()
    summary = {"date": d, "status": "", "started": started.isoformat(timespec="seconds"), "html": "",
               "runs": [], "message": ""}

    def finish(status: str, message: str, st: dict | None = None) -> int:
        summary.update(status=status, message=message, finished=datetime.now().isoformat(timespec="seconds"))
        if st:
            summary["html"] = st.get("html", "")
        write_text_atomic(paths.logs / "latest.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        log(f"[nightly] {status.upper()}  {message}")
        if notify_ and not dry_run and status != "skipped":
            date_jp = f"{int(d[5:7])}/{int(d[8:10])}"
            if status == "success":
                shown = notify(f"📚 {date_jp} の日本語教材ができました", (st or {}).get("theme", ""), summary["html"])
            else:
                shown = notify(f"⚠️ {date_jp} の教材の自動生成に失敗しました", message[:120], str(log.path))
            log(f"[nightly] 通知: {'表示しました' if shown else '表示できませんでした'}")
        return 0 if status in ("success", "skipped") else 1

    log(f"[nightly] 開始  対象日 {d}")
    st = lesson_status(d, paths)
    if complete(st) and not force:
        return finish("skipped", "既に完成しています（--force で作り直し）", st)

    claude = find_claude()
    if not claude:
        return finish("failed", "claude（Claude Code CLI）が見つかりません。CLAUDE_BIN を設定してください")
    if not dry_run and claude_logged_in(claude) is False:
        return finish("failed", LOGIN_HELP, st)
    cmd = claude_cmd(claude)
    resume = None
    if st["exists"] and not complete(st):
        resume = "\n".join(f"- {e}" for e in st["errors"][:15]) or "- data/themes.json に未記録"

    if dry_run:
        log(f"[dry-run] claude: {claude}")
        log(f"[dry-run] コマンド: {' '.join(cmd)}")
        log("[dry-run] プロンプト:\n" + make_prompt(d, resume))
        return finish("skipped", "dry-run（Claude は起動していません）", st)

    try:
        with single_run(paths.logs / "nightly.lock"):
            attempt = transient = 0
            last_transient = ""
            while True:
                n = len(summary["runs"]) + 1
                log(f"[nightly] Claude Code を起動（{n}回目{'・続きから' if resume else ''}）")
                s = run_claude(cmd, make_prompt(d, resume), paths.root, paths.logs / f"{d}-claude.jsonl", log)
                reason = transient_error(s)
                summary["runs"].append({**{k: s[k] for k in ("exit", "timeout", "subtype", "turns", "cost_usd",
                                                             "minutes", "tools")}, "transient": reason})
                log(f"[nightly] Claude 終了  exit={s['exit']} {s['subtype']} turns={s['turns']} tools={s['tools']} "
                    f"{s['minutes']}分{'（時間切れ）' if s['timeout'] else ''}")
                if s["text"]:
                    log("[nightly] Claude の報告:\n" + s["text"].strip())
                st = lesson_status(d, paths)
                if complete(st):
                    break
                if st["exists"]:
                    resume = "\n".join(f"- {e}" for e in st["errors"][:15]) or "- data/themes.json に未記録"
                if reason:
                    last_transient = reason
                    if transient >= len(BACKOFF_SEC):
                        break
                    wait = BACKOFF_SEC[transient]
                    transient += 1
                    log(f"[nightly] 一時的なエラー（{reason}）→ {wait}秒後に再試行（{transient}/{len(BACKOFF_SEC)}）")
                    SLEEP(wait)
                    clear_stale_refresh_lock(log)
                    continue
                log("[nightly] 未完成:\n" + (resume or "- 教材ファイルが作られていません"))
                if attempt >= retries:
                    break
                attempt += 1
                resume = resume or "- 教材ファイルがまだ作られていません（最初から進めてください）"
    except UserError as e:
        return finish("failed", str(e))

    if not complete(st):
        if summary["runs"] and summary["runs"][-1]["transient"]:
            return finish("failed", f"一時的なエラーが続きました（{last_transient}）。しばらくして "
                                    f"lesson nightly {d} で再実行。続く場合は lesson login --force", st)
        return finish("failed", "教材が完成しませんでした（ログを確認）", st)
    if commit:
        git_commit(d, st.get("theme", ""), paths, log)
    return finish("success", f"{st.get('theme', '')} → {st.get('html', '')}", st)


if __name__ == "__main__":
    from common import setup_stdio
    setup_stdio()
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))

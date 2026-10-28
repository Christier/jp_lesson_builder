#!/usr/bin/env python3
"""
schedule.py — Windows タスクスケジューラへの登録・確認・削除。

    lesson schedule install [--time 22:00] [--commit] [--push] [--keep-days N] [--wake] [--visible]   毎日決まった時刻に nightly.cmd を実行
    lesson schedule status                                       次回・前回の実行と結果
    lesson schedule run                                          登録したタスクを今すぐ実行
    lesson schedule uninstall                                    登録を削除

タスクの中身:
  * ログオン中だけ実行（パスワードを保存しない）。PC がその時刻に起きていなければ、
    次に使えるようになったとき実行する（StartWhenAvailable）。
  * 窓は出さない（conhost.exe --headless で nightly.cmd を起動）。終わるとトースト通知。
    ※ PowerShell の -WindowStyle Hidden はタスクから起動すると何も実行せず -1 で終わる環境が
      あった（2026-10-17 この PC で確認）ので使わない。
    ※ headless だとタスクスケジューラの「前回の結果」は常に 0 になる。本当の結果は
      logs/latest.json（lesson schedule status が表示）を見る。--visible なら窓を出し、終了コードも返す。
  * 3時間で強制終了。二重起動はしない。
macOS / Linux では cron の設定例を表示するだけ。
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DEFAULT_PATHS, Paths, UserError  # noqa: E402

TASK = "jp-lesson-builder-nightly"


def _q(s: str) -> str:
    """PowerShell の単一引用符リテラル"""
    return "'" + s.replace("'", "''") + "'"


def _ps(script: str, timeout: int = 60) -> tuple[int, str]:
    script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ErrorActionPreference='Stop';" + script
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-EncodedCommand", enc], capture_output=True, timeout=timeout)
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace")
    out = re.sub(r"#< CLIXML.*", "", out, flags=re.S).strip()  # 進捗表示のゴミを除く
    return r.returncode, out


def task_action(paths: Paths, extra: list[str], visible: bool = False) -> tuple[str, str]:
    """タスクが実行するプログラムと引数。cmd /c ""…" 引数" の形で、空白を含むパスでも壊れない"""
    cmd = str(paths.root / "nightly.cmd")
    inner = f'/c ""{cmd}"{(" " + " ".join(extra)) if extra else ""}"'
    if visible:
        return "cmd.exe", inner
    return "conhost.exe", f"--headless cmd.exe {inner}"


def install_script(paths: Paths, time_: str, extra: list[str], wake: bool, visible: bool = False) -> str:
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", time_):
        raise UserError(f"時刻 '{time_}' は HH:MM 形式で指定してください（例: 22:00）")
    settings = ("New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
                "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew"
                + (" -WakeToRun" if wake else ""))
    exe, arg = task_action(paths, extra, visible)
    return (
        f"$a = New-ScheduledTaskAction -Execute {_q(exe)} -Argument {_q(arg)}"
        f" -WorkingDirectory {_q(str(paths.root))};"
        f"$t = New-ScheduledTaskTrigger -Daily -At {_q(time_)};"
        f"$s = {settings};"
        "$p = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)"
        " -LogonType Interactive -RunLevel Limited;"
        f"Register-ScheduledTask -TaskName {_q(TASK)} -Description {_q('日本語N1教材を毎日自動生成（jp-lesson-builder）')}"
        " -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null;"
        f"$i = Get-ScheduledTask -TaskName {_q(TASK)} | Get-ScheduledTaskInfo;"
        "'次回の実行: ' + $i.NextRunTime"
    )


def _windows() -> bool:
    return sys.platform.startswith("win")


def install(paths: Paths = DEFAULT_PATHS, time_: str = "22:00", commit: bool = False, wake: bool = False,
            visible: bool = False, push: bool = False, keep_days: int = 0) -> int:
    extra = ["--push"] if push else ["--commit"] if commit else []
    if keep_days:
        extra += ["--keep-days", str(keep_days)]
    if not _windows():
        print("Windows 以外では cron に登録してください（crontab -e）:")
        h, m = time_.split(":")
        print(f"  {int(m)} {int(h)} * * *  cd {paths.root} && ./lesson.sh nightly {' '.join(extra)} >> logs/cron.log 2>&1")
        return 0
    rc, out = _ps(install_script(paths, time_, extra, wake, visible))
    if rc:
        raise UserError(f"タスクの登録に失敗しました: {out}")
    print(f"[schedule] 登録しました: {TASK}（毎日 {time_}{'・git commit＋push' if push else '・git commit あり' if commit else ''}"
          f"{f'・直近{keep_days}日分だけ残す' if keep_days else ''}"
          f"{'・スリープ解除' if wake else ''}{'・窓を表示' if visible else '・窓なし'}）")
    print(f"[schedule] {out}")
    return 0


def status(paths: Paths = DEFAULT_PATHS) -> int:
    if _windows():
        rc, out = _ps(
            f"$t = Get-ScheduledTask -TaskName {_q(TASK)} -ErrorAction SilentlyContinue;"
            "if (-not $t) { 'NOT_INSTALLED'; exit 0 };"
            "$i = $t | Get-ScheduledTaskInfo;"
            "'状態        : ' + $t.State;"
            "'次回の実行  : ' + $i.NextRunTime;"
            "'前回の実行  : ' + $i.LastRunTime;"
            "'起動の結果  : ' + $i.LastTaskResult + '（267011=まだ一度も実行していない。生成の成否は下の「直近の実行」）';"
            "'実行内容    : ' + $t.Actions[0].Execute + ' ' + $t.Actions[0].Arguments"
        )
        if "NOT_INSTALLED" in out:
            print(f"[schedule] 未登録です（lesson schedule install で登録）")
        else:
            print(f"[schedule] {TASK}\n{out}")
    latest = paths.logs / "latest.json"
    if latest.exists():
        try:
            j = json.loads(latest.read_text(encoding="utf-8"))
            print(f"\n[nightly] 直近の実行: {j.get('date')}  {j.get('status')}  {j.get('message')}"
                  f"\n          {j.get('started')} 〜 {j.get('finished', '')}")
        except (OSError, json.JSONDecodeError):
            pass
    return 0


def run_now() -> int:
    if not _windows():
        raise UserError("Windows 以外では ./lesson.sh nightly を直接実行してください")
    rc, out = _ps(f"Start-ScheduledTask -TaskName {_q(TASK)}")
    if rc:
        raise UserError(f"起動できませんでした（未登録？）: {out}")
    print("[schedule] 起動しました。進み具合は logs/<日付>-nightly.log、結果は lesson schedule status で確認できます")
    return 0


def uninstall() -> int:
    if not _windows():
        print("cron から該当行を削除してください（crontab -e）")
        return 0
    rc, out = _ps(f"Unregister-ScheduledTask -TaskName {_q(TASK)} -Confirm:$false")
    if rc:
        raise UserError(f"削除できませんでした（未登録？）: {out}")
    print(f"[schedule] 削除しました: {TASK}")
    return 0

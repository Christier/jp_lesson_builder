# jp-lesson-builder

日本語N1教材（単一HTML）を Claude Code で毎日生成するためのプロジェクト。

対話のたびに手で組み立てていた教材を、**「調べる → JSONを書く → ビルド → 検証 → 記録」**の
5工程に分解し、Claude Code に任せられる形にしたもの。Windows / macOS / Linux で同じコマンドが動く。

---

## なぜこの構成にしたか

| これまでの問題 | この構成での解決 |
|---|---|
| HTMLを heredoc で書いて 64KB で切れ、ファイルが破損した | HTMLは書かない。JSONを書き、Pythonがテンプレートから組む（一時ファイル経由で書くので途中で切れたHTMLは残らない） |
| CSS・JS・タブ制御を毎回コピペし、崩れた | `templates/` に固定。中身と見た目が分離 |
| ツールチップのIDずれ・参照漏れ・タグの閉じ忘れに気づけなかった | `validate` が全参照・生HTML・SVGを突き合わせて ERROR を出す |
| 会話全文（TTS用）を手で書き起こしていた | `turns` から自動生成 |
| テーマ・配色が過去と被った | `data/themes.json` を見て自動回避＋警告 |
| 「7/2の復習」のような復習リンクを記憶頼りで書いていた | `lesson record` が `data/vocab-index.json` に自動蓄積、`lesson review` が再登場候補を出す |
| Windows で `make` がない・文字化けで落ちる | `lesson.py` に集約。`lesson.cmd` / `lesson.sh` から起動、出力は常に UTF-8 |

---

## 1. 環境構築（初回のみ・10分）

### 1-1. 前提ソフト

| 必要なもの | 確認コマンド | 備考 |
|---|---|---|
| Python 3.10+ | Windows: `py --version` / mac: `python3 --version` | ビルドに使う |
| Git | `git --version` | 履歴管理（任意だが推奨） |
| Claude Code | `claude --version` | 教材の執筆を任せる |

### 1-2. 依存を入れる（プロジェクト専用の `.venv` を作る）

```powershell
# Windows（PowerShell）
cd C:\workspace\jp_lesson_builder
.\lesson.cmd setup
```

```bash
# macOS / Linux / Git Bash
cd ~/projects/jp_lesson_builder
./lesson.sh setup
```

`setup` は `.venv` を作って `requirements.txt`（Jinja2）を入れ、最後に `doctor` で点検する。
以後 `lesson.cmd` / `lesson.sh` は自動で `.venv` の Python を使うので、仮想環境の有効化は不要。

### 1-3. 動作確認

```powershell
.\lesson.cmd test                  # 自動テスト（65件）
.\lesson.cmd check 2026-09-19      # サンプルをビルド＆検証
.\lesson.cmd open 2026-09-19       # ブラウザで開く
```

`ERROR 0` と表示され、ブラウザに教材が出れば完了。

### 1-4. Claude Code を起動

プロジェクトのルートで `claude` を起動する。`CLAUDE.md` は自動で読み込まれる。

### 1-5. 毎晩22時の自動生成を有効にする（任意）

夜間の自動生成は、Claude Code の **CLI** を非対話モードで起動して行う。
デスクトップアプリのログインは CLI には引き継がれないので、最初に一度だけ CLI でログインする。
（CLI の `claude.exe` は `%USERPROFILE%\.local\bin` に入るが PATH に無いことがあるので、`lesson login` 経由で呼ぶ）

```powershell
.\lesson.cmd login                       # ブラウザでログイン（初回のみ）
.\lesson.cmd nightly --smoke             # 非対話で起動し、./lesson.sh を実行できるか確認 → OK
.\lesson.cmd schedule install --time 22:00
.\lesson.cmd schedule status             # 次回の実行時刻・直近の結果
```

詳しくは「4. 毎晩の自動生成」。

---

## 2. 毎日の使い方（所要 10〜20分）

Claude Code で次を打つだけ:

```
/lesson 2026-09-20
```

日付を省略すると今日の日付になる。Claude Code が以下を自動で実行する:

1. `data/themes.json` と `lesson review` で既出テーマ・再登場させたい語彙を把握
2. WebSearch で対象日の実際のニュースを取材（分野を散らして3本＋見出し5本）
3. `lesson new` で雛形を作り、`drafts/<日付>/` に news・scene・ext を分けて書いて `lesson merge` で結合
4. `lesson check`（build → validate）。ERROR が出たら自分で直して再実行
5. `lesson record` で `data/themes.json` と `data/vocab-index.json` を自動更新
6. 生成内容を日本語で報告

### テーマを指定したいとき

```
/lesson 2026-09-20

会話テーマは「家電量販店でノートPCを買う（延長保証・下取り）」でお願いします。
ニュースは1本、AI・半導体系を入れてください。
```

### その他の Claude Code コマンド

| コマンド | 用途 |
|---|---|
| `/news 2026-09-20` | ニュース取材だけ先にやって `notes/` に保存（朝に走らせておく用） |
| `/review 語彙` | 過去の全教材を横断し、定着済み／要再訪の語彙を仕分け |

---

## 3. 教材ページの使い方

| 機能 | 使い方 |
|---|---|
| ニュースの目次 | ニュースタブ冒頭のカード。分野・読了目安・字数・重要語数が分かり、クリックで記事へ |
| 振り仮名 | 重要語・難読語・固有名詞に付く。上部バーの「ふりがな」で **表示 → タップで表示 → 非表示** を切り替え（「タップで表示」は読みを隠して自分で読む練習用） |
| 解説ポップアップ | ハイライト語をクリック（Tab で選んで Enter でも可）すると、その語のすぐ下に解説。🔊で発音。Esc／外側クリックで閉じる。スマホでは画面下から出る |
| 段落ごとの読み上げ | 各段落の左の ▶。全文再生中は読んでいる段落に色が付く。本文に書いた振り仮名（固有名詞など）は読みのほうで読み上げる |
| ハイライト非表示 | 素の文章で読む練習用 |
| 中文をぼかす | 会話・見出しの中国語訳をぼかし、タップしたものだけ表示（自分で訳してから確認） |
| 文字サイズ | A−／A＋（0.85〜1.5倍） |
| 語彙カードの🔊 | その語を読み上げる |
| メモ欄 | ブラウザに自動保存（教材の日付ごと） |
| 印刷 | 解説をすべて展開した学習シートになる（タブ・ボタン類は印刷されない） |
| 教材一覧 | `dist/index.html`。ビルドのたびに更新される。ブックマークしておくと便利 |

設定（ふりがな・文字サイズなど）はブラウザに保存され、次に開いた教材にも引き継がれる。

---

## 4. 毎晩の自動生成（タスクスケジューラ）

```
タスクスケジューラ（毎日 22:00）
  └ conhost --headless → nightly.cmd → lesson nightly
        1. 対象日を決める（正午より前に動いたら前日分＝取りこぼし分）
        2. 完成済みなら何もしない
        3. claude -p（非対話）に /lesson の手順で取材〜記録まで任せる
        4. 自分で build → validate し直し、記録も確認（未完成なら「続きから」で1回再実行）
        5. logs/ に記録し、トースト通知（クリックで教材が開く）
```

| コマンド | 内容 |
|---|---|
| `schedule install [--time 22:00] [--commit] [--wake] [--visible]` | 登録（`--commit`：完成したら当日分だけ git commit／`--wake`：スリープから起こす／`--visible`：実行中の窓を出す） |
| `schedule status` | 次回の実行時刻と、直近の生成結果（`logs/latest.json`） |
| `schedule run` | 登録したタスクを今すぐ実行 |
| `schedule uninstall` | 登録を削除 |
| `nightly [DATE] [--force] [--dry-run]` | 夜間処理を手動で実行（`nightly.cmd` をダブルクリックしても同じ）。`--dry-run` は Claude を起動せず内容だけ表示 |
| `nightly --smoke` | Claude Code CLI を非対話で起動できるかだけ確認（数秒・教材は作らない） |

- ログ：`logs/<日付>-nightly.log`（進み具合と Claude の最終報告）、`logs/<日付>-claude.jsonl`（全やりとり）、`logs/latest.json`（直近の結果）
- 無人実行で Claude に許すのは `./lesson.sh`・読み取り系コマンド・ファイル編集・Web検索だけ（`rm`・`git push` などは禁止）
- PC がログオンしていないと実行されない（パスワードを保存しないため）。22時にスリープしていた場合は、次に起きたときに実行される
- 使うモデルを固定したいときは環境変数 `LESSON_NIGHTLY_MODEL`、claude の場所が特殊なら `CLAUDE_BIN`

---

## 5. lesson コマンド一覧

Windows は `.\lesson.cmd <コマンド>`（PowerShell なら `.\lesson` でも可）、
macOS / Linux / Git Bash は `./lesson.sh <コマンド>`、`make <コマンド> DATE=...` でも同じ。
`DATE` は `YYYY-MM-DD`、省略すると今日。

| コマンド | 内容 |
|---|---|
| `new [DATE]` | 雛形 `content/<DATE>.json` を作る（ニュース3本分の枠つき・配色自動選択・既存ファイルは上書きしない） |
| `merge [DATE] [FILES…]` | `drafts/<DATE>/*.json`（分割した下書き）を content に結合（トップレベルのキーごとに浅く上書き） |
| `build [DATE]` | JSON → `dist/N1日语学习-<和暦>.html` |
| `validate [DATE]` | 入力JSONと出力HTMLを検証（ERROR があれば終了コード 1） |
| `check [DATE]` | build → validate（執筆中はこれを繰り返す） |
| `record [DATE]` | `index` をもとに `data/themes.json`・`data/vocab-index.json` を更新（ERROR 0 のときだけ。何度実行しても同じ結果） |
| `finish [DATE]` | build → validate → record |
| `open [DATE]` | 生成HTMLを既定のブラウザで開く |
| `rebuild` | `content/*.json` を全部ビルド＆検証（テンプレート改修後の回帰確認） |
| `review [DATE] [--save]` | 語彙の復習レポート（定着候補／要再訪／一度きり／記録漏れ） |
| `nightly` / `schedule` | 毎晩の自動生成（「4. 毎晩の自動生成」） |
| `login [--force]` | Claude Code CLI にログイン（`claude.exe` を自動で探すので PATH 不要。夜間実行の前に一度） |
| `doctor` | Python・Jinja2・データファイル・Claude Code CLI（ログイン状態）の点検 |
| `setup` | `.venv` を作って依存を入れる |
| `test [-v]` | 自動テスト（固定 fixture で動作検証＋本物の全教材が ERROR 0 でビルドできるかの回帰確認。本物の content/data/dist は書き換えない） |

---

## 6. ディレクトリ構成

```
jp_lesson_builder/
├── CLAUDE.md              ★ Claude Codeへの常時指示。教材の品質基準はここ
├── README.md              この手順書
├── lesson.py              ★ 統一コマンド（new / build / validate / record …）
├── lesson.cmd             Windows 用ランチャー（.venv → py → python の順に探す）
├── lesson.sh              macOS / Linux / Git Bash 用ランチャー
├── nightly.cmd            夜間の自動生成（タスクスケジューラから実行。ダブルクリックで今すぐ実行）
├── Makefile               macOS / Linux 向けの薄いラッパー
├── requirements.txt       Jinja2
├── .claude/
│   ├── settings.json      ツール権限の許可リスト
│   └── commands/
│       ├── lesson.md      /lesson — 取材から記録まで通しで実行
│       ├── news.md        /news   — 取材のみ
│       └── review.md      /review — 過去教材の横断復習
├── templates/
│   ├── base.html.j2       HTML骨格（3タブ構成）
│   ├── styles.css.j2      CSS（配色はパレット変数で切替・スマホ対応・印刷用）
│   ├── app.js             タブ・解説ポップアップ・振り仮名切替・TTS（段落単位）・設定とメモの保存
│   └── index.html.j2      教材一覧ページ
├── build/
│   ├── common.py          共通部品（パス・日付・UTF-8出力・アトミック書き込み）
│   ├── new_content.py     当日分JSONの雛形を作る
│   ├── build.py           JSON → HTML
│   ├── validate.py        JSONと出力HTMLを検証
│   ├── record.py          data/ への記録
│   ├── review.py          語彙の復習レポート
│   ├── drafts.py          分割した下書きの結合（lesson merge）
│   ├── nightly.py         夜間の無人実行（lesson nightly）
│   └── schedule.py        タスクスケジューラへの登録（lesson schedule）
├── tests/                 自動テスト（unittest）
│   └── fixtures/data/     テスト用に凍結した themes.json・vocab-index.json（日々の record の影響を受けない）
├── content/               日ごとの教材データ（JSON）＝ここが資産
├── data/
│   ├── palettes.json      配色8種
│   ├── themes.json        会話テーマ使用履歴＋候補リスト
│   └── vocab-index.json   既出語彙インデックス（復習リンク用）
├── notes/                 /news や /review の出力先
├── drafts/                執筆中の下書き（git 管理外）
├── logs/                  夜間実行のログ（git 管理外）
├── tmp/                   改修前のバックアップ zip（git 管理外）
└── dist/                  生成されたHTML（使い捨て。いつでも再生成できる）＋ index.html（一覧）
```

---

## 7. 本文マークアップ（JSONの中で使う記法）

生HTMLを書かせないための軽量記法。ニュースの `paragraphs` と会話の `jp` で使う。

| 記法 | 出力 | 会話で |
|---|---|---|
| `{{v:t1a\|ヘクトパスカル}}` | 黄ハイライト＋ツールチップ `t1a` を開く | ✗ |
| `{{g:t1e\|〜にかけて}}` | 緑ハイライト＋ツールチップ `t1e` を開く | ✗ |
| `{{k:970}}` | キーワード強調 | ○ |
| `{{b:重要}}` | 太字 | ○ |
| `{{br}}` | 改行 | ○ |
| `箕面《みのお》市` | 振り仮名（《》の直前の漢字の連なりに付く） | ○ |
| `大阪府｜箕面《みのお》市` | 振り仮名の範囲を全角 ｜ で指定 | ○ |

**振り仮名の付き方**：ハイライト語は、ツールチップの先頭 `<strong>緊迫（きんぱく）</strong>` から自動で付く
（活用したラベル「膨らみ」にも語幹に付く）。過去の教材で読みを書いた2字以上の語も自動で付く。
それ以外の難読語・固有名詞は本文に《》で書く。振り仮名はどのフィールドでも使える。

それ以外の文字は自動でHTMLエスケープされるので、`<` や `&` を書いても壊れない。

本文・セリフ以外（ツールチップ・解説・カード・表・クイズ・課題など）は生HTMLとして出力される。
使えるのは `<b>` `<strong>` `<br>` `<a>` `<em>` `<span>` などのインライン要素だけ。
SVG図解（`illustrations[].svg`）は整形式のXMLで書く。

JSON の末尾には記録用の `index`（テーマ名と重要語彙・文法5〜10個）を書く。書式は `CLAUDE.md` 参照。

---

## 8. 検証で出るチェック項目

**ERROR（教材として壊れている。必ず直す）**
- JSONが壊れている／必須キーがない／型が違う
- `meta.date`・`date_jp`・`weekday` がファイル名の日付と合わない
- 雛形のプレースホルダー（「見出し——サブ見出し」「分野1」など）が残っている
- 未定義ツールチップの参照、参照されないツールチップ、ID重複、IDに使えない文字
- 閉じていない／未知の `{{ }}`、会話での `{{v:}}` `{{g:}}`
- 生HTMLのタグ閉じ忘れ、`<script>` やイベント属性、壊れたSVG
- 会話が16ターン未満、話者の色が未定義、ロールプレイ・総合チャレンジがない
- クイズが8問未満、空の問題・空の語彙カード、未対応の拡張セクション種別
- 出力HTMLがない／JSONより古い／`</html>` で終わっていない／タブ欠落／テンプレート記法の残留

**WARN（意図的ならOK）**
- 配色・テーマが直近と被っている
- ニュース本文の字数（450〜700字）・ハイライト数（12〜20）・まとめ語彙（6以上）が目安外
- 語彙カードに転用例文がない、見出しが5本未満
- 会話のターン数が18〜24の範囲外、解説付与率が8割未満、SVG図解が2〜4枚の範囲外
- バッジの「〇ターン」「ニュース〇本」が実際と違う
- カジュアル⇔フォーマルの対照表がない、総合チャレンジが「添削します」で締められていない
- `index` がない・空、出力が60KB未満

**INFO（参考）**
- 既出語の一覧（ツールチップに「〇/〇の復習」を書いたかの確認用）、未記録の通知、出力サイズ

---

## 9. 配色パレット

`data/palettes.json` に8種類。`lesson new` が「一番長く使っていないもの」を自動選択する。

`teal` / `violet` / `orange` / `crimson` / `sky` / `emerald` / `indigo` / `autumn`

新しい配色を足すときは、既存エントリと同じキー構成でJSONに追記するだけ（未使用の配色が最優先で選ばれる）。

---

## 10. 運用のコツ

- **`content/*.json` が本当の資産。** HTMLは使い捨て。テンプレートを改善したら
  `lesson rebuild` で過去の全教材が新デザインで作り直せ、同時に全件検証される。
- **`data/vocab-index.json` を育てる。** 毎回 `index.terms` を書いて `lesson record` するだけで、
  「毎日バラバラの教材」が「積み上がるカリキュラム」に変わる。
- **朝に `/news` だけ走らせておく**と、夜の `/lesson` が速い。
- **Git にコミットしておく。** data/ の JSON は1エントリ1行で書かれるので、差分で「先週どんな語彙をやったか」が追える。
- 教材ページのメモ欄はブラウザに自動保存される（同じブラウザで開き直せば残っている）。

---

## 11. よくあるトラブル

| 症状 | 対処 |
|---|---|
| `Python was not found; run without arguments to install from the Microsoft Store` | Windows の「アプリ実行エイリアス」が `python` を乗っ取っている。`lesson.cmd` / `lesson.sh` は `.venv` → `py` の順に探すので、そちらから実行する（`.\lesson.cmd setup` 済みなら影響なし） |
| `UnicodeEncodeError: 'cp932' codec …` | 旧版の症状。現行版は出力を UTF-8 に固定済み。`lesson.cmd` / `lesson.sh` 経由で実行する |
| `Jinja2 がインストールされていません` | `lesson setup` を実行 |
| `JSONの構造が不足・不正なため…` | `lesson validate <日付>` が原因箇所を教えてくれる |
| `JSONがHTMLより新しくなっています` | `lesson check <日付>`（build してから validate） |
| `make: command not found`（Windows） | make は不要。`.\lesson.cmd <コマンド>` を使う |
| 夜間実行が「Claude Code（CLI）にログインしていません」で失敗 | `.\lesson.cmd login` を一度実行し、`.\lesson.cmd nightly --smoke` で OK を確認 |
| `claude : 用語 'claude' は、コマンドレット…として認識されません` | `claude.exe` が PATH に無い（`%USERPROFILE%\.local\bin`）。`.\lesson.cmd login` を使えば PATH は不要 |
| 夜間実行が「別の nightly が実行中です」 | 本当に動いていなければ `logs/nightly.lock` を削除（6時間たてば自動で外れる） |
| 夜間実行で教材が完成しなかった | `logs/<日付>-nightly.log` に未完成の理由（validate の ERROR）がある。`.\lesson.cmd nightly <日付>` で続きから再実行できる |
| ログに `Failed to refresh OAuth token: another Claude Code process is refreshing it…` | ちょうどトークンの更新時刻に、別の Claude Code（デスクトップアプリ等）と更新がぶつかった一時的なエラー。nightly は 1→2→5→10 分の間隔で自動的に再試行し、10分以上残った更新ロック（`%USERPROFILE%\.claude\.oauth_refresh.lock`）も外す。それでも続くときは `.\lesson.cmd login --force` |
| タスクスケジューラの「前回の結果」が 0 なのに失敗している | 窓なし起動（conhost --headless）は終了コードを返さない。本当の結果は `lesson schedule status` の「直近の実行」を見る |
| 振り仮名が長い範囲に付いてしまう | 《》は直前の漢字の連なり全体に付く。`大阪府｜箕面《みのお》市` のように ｜ で範囲を指定（validate が WARN で教える） |
| TTSが鳴らない／途中で止まる | Chrome か Edge で開く（Edge の「Natural」音声が自然）。長文は文単位で順に読むので途中停止は起きにくい。止まったら再読み込み |
| Claude Code が CLAUDE.md を読んでいない | プロジェクトのルートで `claude` を起動しているか確認。`/memory` で確認できる |

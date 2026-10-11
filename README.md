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
.\lesson.cmd test                  # 自動テスト（43件）
.\lesson.cmd check 2026-09-19      # サンプルをビルド＆検証
.\lesson.cmd open 2026-09-19       # ブラウザで開く
```

`ERROR 0` と表示され、ブラウザに教材が出れば完了。

### 1-4. Claude Code を起動

プロジェクトのルートで `claude` を起動する。`CLAUDE.md` は自動で読み込まれる。

---

## 2. 毎日の使い方（所要 10〜20分）

Claude Code で次を打つだけ:

```
/lesson 2026-09-20
```

日付を省略すると今日の日付になる。Claude Code が以下を自動で実行する:

1. `data/themes.json` と `lesson review` で既出テーマ・再登場させたい語彙を把握
2. WebSearch で対象日の実際のニュースを取材（分野を散らして3本＋見出し5本）
3. `lesson new` で雛形を作り、`content/<日付>.json` を執筆
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

## 3. lesson コマンド一覧

Windows は `.\lesson.cmd <コマンド>`（PowerShell なら `.\lesson` でも可）、
macOS / Linux / Git Bash は `./lesson.sh <コマンド>`、`make <コマンド> DATE=...` でも同じ。
`DATE` は `YYYY-MM-DD`、省略すると今日。

| コマンド | 内容 |
|---|---|
| `new [DATE]` | 雛形 `content/<DATE>.json` を作る（ニュース3本分の枠つき・配色自動選択・既存ファイルは上書きしない） |
| `build [DATE]` | JSON → `dist/N1日语学习-<和暦>.html` |
| `validate [DATE]` | 入力JSONと出力HTMLを検証（ERROR があれば終了コード 1） |
| `check [DATE]` | build → validate（執筆中はこれを繰り返す） |
| `record [DATE]` | `index` をもとに `data/themes.json`・`data/vocab-index.json` を更新（ERROR 0 のときだけ。何度実行しても同じ結果） |
| `finish [DATE]` | build → validate → record |
| `open [DATE]` | 生成HTMLを既定のブラウザで開く |
| `rebuild` | `content/*.json` を全部ビルド＆検証（テンプレート改修後の回帰確認） |
| `review [DATE] [--save]` | 語彙の復習レポート（定着候補／要再訪／一度きり／記録漏れ） |
| `doctor` | Python・Jinja2・データファイルの点検 |
| `setup` | `.venv` を作って依存を入れる |
| `test [-v]` | 自動テスト（固定 fixture で動作検証＋本物の全教材が ERROR 0 でビルドできるかの回帰確認。本物の content/data/dist は書き換えない） |

---

## 4. ディレクトリ構成

```
jp_lesson_builder/
├── CLAUDE.md              ★ Claude Codeへの常時指示。教材の品質基準はここ
├── README.md              この手順書
├── lesson.py              ★ 統一コマンド（new / build / validate / record …）
├── lesson.cmd             Windows 用ランチャー（.venv → py → python の順に探す）
├── lesson.sh              macOS / Linux / Git Bash 用ランチャー
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
│   ├── styles.css.j2      CSS（配色はパレット変数で切替）
│   └── app.js             タブ・ツールチップ・TTS（文単位で読み上げ）・メモ自動保存
├── build/
│   ├── common.py          共通部品（パス・日付・UTF-8出力・アトミック書き込み）
│   ├── new_content.py     当日分JSONの雛形を作る
│   ├── build.py           JSON → HTML
│   ├── validate.py        JSONと出力HTMLを検証
│   ├── record.py          data/ への記録
│   └── review.py          語彙の復習レポート
├── tests/                 自動テスト（unittest）
│   └── fixtures/data/     テスト用に凍結した themes.json・vocab-index.json（日々の record の影響を受けない）
├── content/               日ごとの教材データ（JSON）＝ここが資産
├── data/
│   ├── palettes.json      配色8種
│   ├── themes.json        会話テーマ使用履歴＋候補リスト
│   └── vocab-index.json   既出語彙インデックス（復習リンク用）
├── notes/                 /news や /review の出力先
└── dist/                  生成されたHTML（使い捨て。いつでも再生成できる）
```

---

## 5. 本文マークアップ（JSONの中で使う記法）

生HTMLを書かせないための軽量記法。ニュースの `paragraphs` と会話の `jp` で使う。

| 記法 | 出力 | 会話で |
|---|---|---|
| `{{v:t1a\|ヘクトパスカル}}` | 黄ハイライト＋ツールチップ `t1a` を開く | ✗ |
| `{{g:t1e\|〜にかけて}}` | 緑ハイライト＋ツールチップ `t1e` を開く | ✗ |
| `{{k:970}}` | キーワード強調 | ○ |
| `{{b:重要}}` | 太字 | ○ |
| `{{br}}` | 改行 | ○ |

それ以外の文字は自動でHTMLエスケープされるので、`<` や `&` を書いても壊れない。

本文・セリフ以外（ツールチップ・解説・カード・表・クイズ・課題など）は生HTMLとして出力される。
使えるのは `<b>` `<strong>` `<br>` `<a>` `<em>` `<span>` などのインライン要素だけ。
SVG図解（`illustrations[].svg`）は整形式のXMLで書く。

JSON の末尾には記録用の `index`（テーマ名と重要語彙・文法5〜10個）を書く。書式は `CLAUDE.md` 参照。

---

## 6. 検証で出るチェック項目

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

## 7. 配色パレット

`data/palettes.json` に8種類。`lesson new` が「一番長く使っていないもの」を自動選択する。

`teal` / `violet` / `orange` / `crimson` / `sky` / `emerald` / `indigo` / `autumn`

新しい配色を足すときは、既存エントリと同じキー構成でJSONに追記するだけ（未使用の配色が最優先で選ばれる）。

---

## 8. 運用のコツ

- **`content/*.json` が本当の資産。** HTMLは使い捨て。テンプレートを改善したら
  `lesson rebuild` で過去の全教材が新デザインで作り直せ、同時に全件検証される。
- **`data/vocab-index.json` を育てる。** 毎回 `index.terms` を書いて `lesson record` するだけで、
  「毎日バラバラの教材」が「積み上がるカリキュラム」に変わる。
- **朝に `/news` だけ走らせておく**と、夜の `/lesson` が速い。
- **Git にコミットしておく。** data/ の JSON は1エントリ1行で書かれるので、差分で「先週どんな語彙をやったか」が追える。
- 教材ページのメモ欄はブラウザに自動保存される（同じブラウザで開き直せば残っている）。

---

## 9. よくあるトラブル

| 症状 | 対処 |
|---|---|
| `Python was not found; run without arguments to install from the Microsoft Store` | Windows の「アプリ実行エイリアス」が `python` を乗っ取っている。`lesson.cmd` / `lesson.sh` は `.venv` → `py` の順に探すので、そちらから実行する（`.\lesson.cmd setup` 済みなら影響なし） |
| `UnicodeEncodeError: 'cp932' codec …` | 旧版の症状。現行版は出力を UTF-8 に固定済み。`lesson.cmd` / `lesson.sh` 経由で実行する |
| `Jinja2 がインストールされていません` | `lesson setup` を実行 |
| `JSONの構造が不足・不正なため…` | `lesson validate <日付>` が原因箇所を教えてくれる |
| `JSONがHTMLより新しくなっています` | `lesson check <日付>`（build してから validate） |
| `make: command not found`（Windows） | make は不要。`.\lesson.cmd <コマンド>` を使う |
| TTSが鳴らない／途中で止まる | Chrome か Edge で開く（Edge の「Natural」音声が自然）。長文は文単位で順に読むので途中停止は起きにくい。止まったら再読み込み |
| Claude Code が CLAUDE.md を読んでいない | プロジェクトのルートで `claude` を起動しているか確認。`/memory` で確認できる |

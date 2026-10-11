---
description: 過去教材を横断して、語彙の復習リストや弱点マップを作る
argument-hint: [語彙|文法|テーマ]
allowed-tools: Bash(./lesson.sh:*), Bash(date:*), Read, Glob, Grep, Write
---

`content/*.json` と `data/vocab-index.json` を横断して、$ARGUMENTS の観点で復習資料を作る。

やること：
1. `./lesson.sh review --save` を実行する。vocab-index を集計し、
   `notes/review-<今日>.md` に次の分類を書き出す（集計は機械的に正確なので手で数え直さない）
   - **定着候補**（3回以上登場）… もう説明不要。使えるか確認する段階
   - **要再訪**（2回登場、最終出現から3週間以上）… 次の教材で再登場させる
   - **一度きり**（1回のみ）… 重要度を判断し、重要なら再登場リストへ
   - **記録漏れ**（content の index.terms にあるのに vocab-index に未記録）
2. 記録漏れがあれば、該当日について `./lesson.sh record <日付>` を実行して整合させる
3. `content/*.json` のツールチップと語彙カードも読み、index に載っていないが重要な語を拾う
   （該当日の content の `index.terms` に追記してから `./lesson.sh record <日付>`）
4. $ARGUMENTS の観点でコメントを `notes/review-<今日>.md` に追記し、
   次回教材で優先的に再登場させるべき語彙を10個、理由付きで提案する

`data/*.json` は手で編集しない（必ず `lesson record` 経由）。

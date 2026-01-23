# DIFF SPECIFICATION

## 正本
- v5.2 frozen (backup_v5.2_lite_v3_frozen_20260115)

## 差分（この1点のみ）
- 各銘柄に「投資判断補助ニュース」を最大1本追加

## 実装ルール
- 既存ニュース配列の末尾に append
- 既存ニュース描画ロジックを再利用
- email_template_v5.py は原則無変更
  - 変更が必要な場合でも if 分岐1行まで

## 明示的にやらないこと
- 企業ニュース0件問題への介入
- Auto-Pick / Forced-Pick 表示
- セクション追加
- デザイン変更

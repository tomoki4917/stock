# 宿題の自動生成（毎朝4:00 JST）

## 仕組み
1. GitHub Actions（`.github/workflows/daily-homework.yml`）が毎日 04:00 JST に起動する
2. ワークフローが `DAILY.md` の内容をプロンプトにして Cursor Cloud Agents API を呼ぶ
3. Cloud Agent が市場ニュースを調べ、`宿題/YYYY-MM-DD_*.md` を作成して main に push する

## 必要なシークレット（1回だけ）
- 名前: `CURSOR_API_KEY`
- 発行: https://cursor.com/dashboard/api
- 登録先: GitHub リポジトリ → Settings → Secrets and variables → Actions

## 手動テスト
Actions → Daily homework → Run workflow

## エージェント指示
本文はリポジトリ直下の `DAILY.md`（このファイルと同内容）を正とする。

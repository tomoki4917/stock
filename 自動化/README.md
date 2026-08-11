# 宿題の自動生成（毎朝4:00 JST）

## 仕組み
1. GitHub Actions（`.github/workflows/daily-homework.yml`）が毎日 04:00 JST に起動する
2. ワークフローが `DAILY.md` と `監視銘柄.json` をプロンプトに含めて Cursor Cloud Agents API を呼ぶ
3. Cloud Agent が市場ニュース＋監視銘柄の材料を調べ、`宿題/YYYY-MM-DD_*.md` を作成して main に push する

## 監視銘柄
- データ: リポジトリ直下の `監視銘柄.json`
- 編集: スマホアプリ「宿題ノート」→ **監視銘柄** からフォーム入力して保存
- 宿題は監視銘柄をローテーションしながら、実践スキル（売買判断・指標の読み方など）を毎日1つずつ積み上げる

## 必要なシークレット（1回だけ）
- 名前: `CURSOR_API_KEY`
- 発行: https://cursor.com/dashboard/api
- 登録先: GitHub リポジトリ → Settings → Secrets and variables → Actions

## 手動テスト
Actions → Daily homework → Run workflow

## エージェント指示
本文はリポジトリ直下の `DAILY.md`（このファイルと同内容）を正とする。

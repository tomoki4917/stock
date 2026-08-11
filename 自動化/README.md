# 宿題の自動生成（毎朝4:00 JST）

## 仕組み
1. GitHub Actions（`.github/workflows/daily-homework.yml`）が毎日 04:00 JST に起動する
2. ワークフローが `DAILY.md` と `監視銘柄.json` をプロンプトに含めて Cursor Cloud Agents API を呼ぶ
3. Cloud Agent が市場ニュース＋監視銘柄の材料を調べ、`宿題/YYYY-MM-DD_*.md` を作成して main に push する

## 監視銘柄
- データ: リポジトリ直下の `監視銘柄.json`
- 編集: スマホアプリ「宿題ノート」→ **監視銘柄** からフォーム入力して保存
- 宿題は監視銘柄をローテーションしながら、実践スキル（売買判断・指標の読み方など）を毎日1つずつ積み上げる

## 添削（宿題回答後）
1. 宿題ノートアプリで回答を保存 →「宿題回答（スマホから）」で push
2. GitHub Actions（`homework-feedback.yml`）が FEEDBACK.md をプロンプトに Cursor Agent を起動
3. Agent が「AIフィードバック: <ファイル名>」で commit & push
4. アプリが添削到着を検知して表示

## 必要なシークレット
| Secret | 用途 | 必須 |
|--------|------|------|
| `GEMINI_API_KEY` | 宿題添削（Gemini API） | ✅ |
| `GEMINI_MODEL` | 使用モデル（例: `gemini-2.5-flash`） | 任意 |
| `CURSOR_API_KEY` | 毎朝4時の宿題生成 | ✅ |

発行: https://aistudio.google.com/apikey
登録先: GitHub → Settings → Secrets and variables → Actions

## 手動テスト
Actions → Daily homework → Run workflow

## エージェント指示
本文はリポジトリ直下の `DAILY.md`（このファイルと同内容）を正とする。

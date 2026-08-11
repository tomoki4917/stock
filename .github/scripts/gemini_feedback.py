#!/usr/bin/env python3
"""Generate homework feedback via Gemini API and commit results."""

import json
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request


DEFAULT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
]


def parse_questions(text: str):
    lines = text.splitlines()
    q_starts = []
    ai_header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("### Q"):
            m = re.match(r"^###\s+(Q\d+)\b", line)
            if m:
                q_starts.append((m.group(1), i))
        if line.startswith("## AIからのフィードバック"):
            ai_header_idx = i
    q_starts_sorted = sorted(q_starts, key=lambda x: x[1])

    sections = []
    for idx, (qkey, start) in enumerate(q_starts_sorted):
        end = ai_header_idx if ai_header_idx is not None else len(lines)
        if idx + 1 < len(q_starts_sorted):
            end = q_starts_sorted[idx + 1][1]
        answer_lines = []
        answer_start = answer_end = None
        j = start
        while j < end:
            if lines[j].startswith(">"):
                answer_start = j
                k = j
                while k < end and lines[k].startswith(">"):
                    answer_lines.append(lines[k])
                    k += 1
                answer_end = k - 1
                j = k
                break
            j += 1
        joined = "\n".join(ln.lstrip("> ").rstrip() for ln in answer_lines).strip()
        answered = bool(joined) and joined != "（ここに記入）"
        sections.append(
            {
                "qkey": qkey,
                "start": start,
                "end": end,
                "answer_start": answer_start,
                "answer_end": answer_end,
                "answer_text": joined,
                "answered": answered,
            }
        )
    return sections, ai_header_idx, lines


def extract_prompt_parts(file_text: str):
    sections, _, _ = parse_questions(file_text)
    payload = []
    for s in sections:
        if s["answered"]:
            payload.append({"question": s["qkey"], "answer": s["answer_text"]})
    return payload


def call_gemini(model: str, prompt: str) -> dict:
    api_key = os.environ["GEMINI_API_KEY"]
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            # structured output（responseSchema）を使わないことで互換性エラーを回避する
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini HTTP {exc.code} ({model}): {err_body[:500]}") from exc

    if "error" in data:
        raise RuntimeError(f"Gemini error ({model}): {json.dumps(data['error'], ensure_ascii=False)}")

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates ({model})")

    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    if not text:
        raise RuntimeError(f"Gemini returned empty text ({model})")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise RuntimeError(f"Gemini output is not JSON ({model}): {text[:300]}")
        return json.loads(m.group(0))


def gemini_generate(payload, feedback_md, watchlist_text, tz_date):
    # responseSchema は使わず、「JSONだけ返す」ことを強制する
    prompt = (
        f"{feedback_md}\n\n"
        f"--- 対象宿題（学生回答のみ） ---\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        f"--- 追加情報 ---\n"
        f"監視銘柄.json:\n{watchlist_text}\n\n"
        f"今日の日付: {tz_date}\n\n"
        "出力は必ず JSON のみ（前後に文章を入れない）。"
        "JSONスキーマは次の形にすること:\n"
        "{\n"
        '  "q_comments": { "Q1": ["良い点", "惜しい点/訂正", "次に調べる用語"], "Q2": ["...","...","..."] },\n'
        '  "overall": ["総評（短く）"]\n'
        "}\n"
    )

    preferred = os.environ.get("GEMINI_MODEL", "").strip()
    models = [preferred] if preferred else []
    for model in DEFAULT_MODELS:
        if model not in models:
            models.append(model)

    last_error = None
    for model in models:
        try:
            print(f"Calling Gemini model: {model}")
            return call_gemini(model, prompt)
        except RuntimeError as exc:
            last_error = exc
            print(f"Model failed: {exc}", file=sys.stderr)
    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")


def rewrite_file(path: str, feedback_md: str, watchlist_text: str, tz_date: str):
    with open(path, "r", encoding="utf-8") as f:
        original = f.read()

    sections, ai_header_idx, lines = parse_questions(original)
    payload = extract_prompt_parts(original)
    if not payload:
        print(f"No answered questions in {path}")
        return False

    model_out = gemini_generate(payload, feedback_md, watchlist_text, tz_date)
    q_comments = model_out.get("q_comments", {})
    overall = model_out.get("overall", ["総評: ありがとうございました。"])

    insert_map = {}
    for s in sections:
        if not s["answered"]:
            continue
        ans_end = s["answer_end"]
        if ans_end is None:
            continue
        bullets = q_comments.get(s["qkey"])
        if not bullets:
            continue
        block = [f"**AIコメント（{tz_date}）**"]
        block.extend(f"- {b}" for b in bullets[:3])
        insert_map[ans_end] = block

    out_lines = []
    for i, line in enumerate(lines):
        out_lines.append(line)
        if i in insert_map:
            out_lines.extend(insert_map[i])

    if ai_header_idx is not None:
        new_out = []
        i = 0
        while i < len(out_lines):
            line = out_lines[i]
            if line.startswith("## AIからのフィードバック"):
                new_out.append(line)
                i += 1
                while (
                    i < len(out_lines)
                    and out_lines[i].strip().startswith(">")
                    and "（未提出）" in out_lines[i]
                ):
                    i += 1
                new_out.extend(
                    [
                        "",
                        f"**総評（{tz_date}時点）**",
                        *[f"- {x}" for x in overall],
                        "",
                    ]
                )
                continue
            new_out.append(line)
            i += 1
        out_text = "\n".join(new_out) + "\n"
    else:
        out_text = "\n".join(out_lines) + "\n"

    if out_text == original:
        print(f"No changes needed for {path}")
        return False

    with open(path, "w", encoding="utf-8") as f:
        f.write(out_text)
    return True


def git_push():
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        remote = (
            f"https://x-access-token:{token}@github.com/"
            f"{os.environ.get('GITHUB_REPOSITORY', 'tomoki4917/stock')}.git"
        )
        subprocess.check_call(["git", "push", remote, "HEAD:main"])
    else:
        subprocess.check_call(["git", "push", "origin", "HEAD:main"])


def main():
    changed_files = os.environ.get("CHANGED_FILES", "").split()
    changed_files = [f for f in changed_files if f]
    if not changed_files:
        print("No changed homework files.")
        return

    with open("FEEDBACK.md", "r", encoding="utf-8") as f:
        feedback_md = f.read()

    watchlist_text = ""
    if os.path.exists("監視銘柄.json"):
        with open("監視銘柄.json", "r", encoding="utf-8") as f:
            watchlist_text = f.read()

    tz_date = subprocess.check_output(["date", "+%m/%d"], text=True).strip()

    changed_any = False
    for path in changed_files:
        print(f"Processing {path}")
        if rewrite_file(path, feedback_md, watchlist_text, tz_date):
            changed_any = True

    if not changed_any:
        print("No files needed rewriting.")
        return

    subprocess.check_call(["git", "config", "user.name", "github-actions[bot]"])
    subprocess.check_call(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"]
    )
    subprocess.check_call(["git", "add", "宿題"])
    commit_target = changed_files[0]
    subprocess.check_call(["git", "commit", "-m", f"AIフィードバック: {commit_target}"])
    git_push()
    print("Feedback committed and pushed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Actions のジョブログがAPIで取得しにくいことがあるため、
        # 例外内容をリポジトリ内へ（.debug/）書き出して確認できるようにする。
        try:
            os.makedirs(".debug", exist_ok=True)
            ts = int(time.time())
            err_path = f".debug/gemini_error_{ts}.txt"
            with open(err_path, "w", encoding="utf-8") as f:
                f.write("ERROR: " + str(exc) + "\n\n")
                f.write(traceback.format_exc())
            subprocess.check_call(["git", "config", "user.name", "github-actions[bot]"])
            subprocess.check_call(
                ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"]
            )
            subprocess.check_call(["git", "add", err_path])
            subprocess.check_call(["git", "commit", "-m", f"Gemini debug: {ts}"])
            # push して確認できるようにする（添削結果は失敗のままでOK）
            git_push()
        except Exception:
            # デバッグコミット自体に失敗しても元のエラーは失敗として返す
            pass

        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

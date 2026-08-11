#!/usr/bin/env python3
"""Generate homework feedback via Gemini API and commit results."""

import json
import os
import re
import subprocess
import sys


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


def gemini_generate(payload, feedback_md, watchlist_text, tz_date):
    api_key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

    prompt = (
        f"{feedback_md}\n\n"
        f"--- 対象宿題（学生回答のみ） ---\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        f"--- 追加情報 ---\n"
        f"監視銘柄.json:\n{watchlist_text}\n\n"
        f"今日の日付: {tz_date}\n\n"
        "出力要件（最重要）:\n"
        "1) 返信は JSON だけ（前後に文章を付けない）\n"
        "2) JSON スキーマ:\n"
        "{\n"
        '  "q_comments": {\n'
        '    "Q1": ["良い点: ...", "惜しい点/訂正: ...", "次に調べる用語: ..."],\n'
        '    "Q2": ["...","...","..."]\n'
        "  },\n"
        '  "overall": ["総評（短く）: ..."]\n'
        "}\n"
        "3) 各 Q コメント配列は必ず3要素\n"
        "4) 用語や指摘は初心者向けに短く、事実/推測を分けて書く\n"
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4},
    }
    res = subprocess.check_output(
        [
            "curl",
            "-sS",
            "-X",
            "POST",
            url,
            "-H",
            "Content-Type: application/json",
            "--data",
            json.dumps(body, ensure_ascii=False),
        ],
        text=True,
    )
    data = json.loads(res)
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], ensure_ascii=False))

    text = data["candidates"][0]["content"]["parts"][0].get("text", "")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("Gemini output does not contain JSON")
    return json.loads(m.group(0))


def rewrite_file(path: str, feedback_md: str, watchlist_text: str, tz_date: str):
    with open(path, "r", encoding="utf-8") as f:
        original = f.read()

    sections, ai_header_idx, lines = parse_questions(original)
    payload = extract_prompt_parts(original)
    if not payload:
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
        block.extend(f"- {b}" for b in bullets)
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
        return False

    with open(path, "w", encoding="utf-8") as f:
        f.write(out_text)
    return True


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
    subprocess.check_call(["git", "push"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

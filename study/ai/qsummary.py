#!/usr/bin/env python3
"""頭に入る版（q.sum）を各問の6社解説から組み立てる。

元の定時ジョブ版 qsummary.py はリポジトリ外（手元Mac）で LLM を呼んでいた。
本スクリプトはそのスキーマ互換の抽出版で、外部 API なしで欠落分を埋める。
LLM で作り直すときは --force で上書きできる。

Usage:
  python3 study/ai/qsummary.py              # 欠落のみ埋める
  python3 study/ai/qsummary.py --force      # 全問再生成（既存 sum も上書き）
  python3 study/ai/qsummary.py --dry-run    # 件数だけ表示
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
JST = timezone(timedelta(hours=9))
CORE = ["ChatGPT", "Claude", "Gemini", "Grok", "Copilot", "NotebookLM"]
ORDER = CORE + ["その他"]

W_ANS, W_ART, W_CASE, W_SEC, W_LEN = 40, 20, 15, 15, 10

OX_MAP = {"◯": "○", "〇": "○", "✕": "×", "x": "×", "X": "×"}
LEG_SPLIT = re.compile(
    r"(?m)^(?:#{1,4}\s*)?(?:\*\*)?(?:肢\s*)?([ア-ン]|[1-9]|[１２３４５６７８９])[）)\s．.、:：\*]*"
)
JUDGE = re.compile(r"判定\s*[:：]\s*([○◯〇×✕xX])")
REASON = re.compile(r"理由\s*[:：]\s*(.+)")
POINT = re.compile(r"切るポイント\s*[:：]\s*(.+)")
QUOTE = re.compile(r"[「『]([^」』]{2,40})[」』]")
ART_LINE = re.compile(
    r"(?:^|\n)\s*(?:\*\*)?((?:民法|刑法|憲法|会社法|商法|手形法|小切手法|民訴法|"
    r"民事訴訟法|刑訴法|刑事訴訟法|行政事件訴訟法|行訴法|行政手続法|国賠法|"
    r"少年法|労働組合法|労働基準法|特許法|著作権法|不正競争防止法|"
    r"地方自治法|公職選挙法|戸籍法|供託法|破産法|民事執行法|民事保全法)"
    r"[^\n*]{0,40}?条[^\n*]{0,20}?)(?:\*\*)?"
)


def na(s: str) -> str:
    return "".join(sorted(re.findall(r"\d", s or "")))


def ox(s: str) -> str:
    s = (s or "").strip()
    return OX_MAP.get(s, s)


def sec(ai: dict, mark: str) -> str:
    for k, v in (ai.get("sections") or {}).items():
        if k.startswith(mark):
            return v or ""
    return ""


def first_sentence(text: str, limit: int = 120) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"^#+\s*", "", t)
    t = re.sub(r"\*\*", "", t)
    if not t:
        return ""
    m = re.split(r"(?<=[。．!?！？])\s*", t, maxsplit=1)
    s = m[0] if m else t
    return s[:limit].rstrip("、, ")


def pick_zu(q: dict, rank: list[str]) -> str:
    best, best_n = (rank[0] if rank else ""), -1
    for a in rank or list((q.get("ai") or {}).keys()):
        n = len(sec(q["ai"][a], "②").strip())
        if n > best_n:
            best, best_n = a, n
    return best


def ais(q: dict) -> list[str]:
    ai = q.get("ai") or {}
    return [a for a in ORDER if a in ai] + [a for a in ai if a not in ORDER]


def ai_rank(q: dict) -> dict[str, Any] | None:
    A = ais(q)
    if not A:
        return None
    half = max(2, (len(A) + 1) // 2)

    def tally(field: str) -> dict[str, int]:
        m: dict[str, int] = {}
        for a in A:
            for x in set(q["ai"][a].get(field) or []):
                m[x] = m.get(x, 0) + 1
        return m

    art_t, case_t = tally("articles"), tally("cases")
    c_arts = [k for k, n in art_t.items() if n >= half]
    c_cases = [k for k, n in case_t.items() if n >= half]
    labels = sorted({lb for a in A for lb in (q["ai"][a].get("choices") or {})})

    def maj(vs: list[str]) -> str | None:
        c: dict[str, int] = {}
        for v in vs:
            if v:
                c[v] = c.get(v, 0) + 1
        e = sorted(c.items(), key=lambda x: -x[1])
        if e and (len(e) == 1 or e[0][1] > e[1][1]):
            return e[0][0]
        return None

    maj_ans = maj([na(q["ai"][a].get("answer") or "") for a in A])
    maj_ch = {lb: maj([(q["ai"][a].get("choices") or {}).get(lb) for a in A]) for lb in labels}
    rv = q.get("review") or {}

    def chars_of(a: str) -> int:
        if rv.get(a) and rv[a].get("chars"):
            return int(rv[a]["chars"])
        return len("".join((q["ai"][a].get("sections") or {}).values()))

    max_chars = max(1, *(chars_of(a) for a in A))
    ronbun = not labels and not any(q["ai"][a].get("answer") for a in A)
    want_secs = 5 if ronbun else 7
    per: dict[str, Any] = {}
    for a in A:
        g = q["ai"][a]
        arts, cases = set(g.get("articles") or []), set(g.get("cases") or [])
        secs = len(g.get("sections") or {})
        chars = chars_of(a)
        ax, good, warn = [], [], []
        shaky = False
        if maj_ans or labels:
            v = 1.0
            if maj_ans:
                if not g.get("answer"):
                    v, warn = 0.35, warn + ["正解を書いていない"]
                elif na(g.get("answer") or "") != maj_ans:
                    v, shaky = 0.0, True
                    warn.append("正解が他AIと違う")
                else:
                    good.append("正解一致")
            ng = [
                lb
                for lb in labels
                if (g.get("choices") or {}).get(lb)
                and maj_ch.get(lb)
                and g["choices"][lb] != maj_ch[lb]
            ]
            if ng:
                v = max(0.0, v - 0.34 * len(ng))
                shaky = True
                warn.append("肢○×が他AIと逆")
            ax.append((W_ANS, v))
        if c_arts:
            miss = [x for x in c_arts if x not in arts]
            ax.append((W_ART, 1 - len(miss) / len(c_arts)))
            if not miss:
                good.append(f"条文{len(c_arts)}件すべてに触れた")
        if c_cases:
            miss = [x for x in c_cases if x not in cases]
            ax.append((W_CASE, 1 - len(miss) / len(c_cases)))
            if not miss:
                good.append(f"判例{len(c_cases)}件すべてに触れた")
        ax.append((W_SEC, min(1.0, secs / want_secs)))
        ax.append((W_LEN, chars / max_chars))
        wsum = sum(w for w, _ in ax) or 1
        score = round(100 * sum(w * max(0, min(1, v)) for w, v in ax) / wsum)
        per[a] = {"score": score, "chars": chars, "secs": secs, "good": good, "warn": warn, "shaky": shaky}
    rank = sorted(A, key=lambda a: (-per[a]["score"], -per[a]["chars"]))
    return {"per": per, "rank": rank, "ronbun": ronbun, "maj_ans": maj_ans, "maj_ch": maj_ch}


def split_legs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not text:
        return out
    hits = list(LEG_SPLIT.finditer(text))
    if len(hits) < 2:
        return out
    for i, m in enumerate(hits):
        lab = m.group(1)
        if lab in "１２３４５６７８９":
            lab = str("１２３４５６７８９".index(lab) + 1)
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        chunk = text[m.start() : end].strip()
        if lab not in out:
            out[lab] = chunk
    return out


def one_liner(chunk: str, fallback: str = "") -> str:
    if not chunk:
        return fallback
    m = REASON.search(chunk)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        t = re.sub(r"\*\*", "", t)
        return t[:90]
    # first non-empty bullet / line after the label line
    lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
    for ln in lines[1:6]:
        ln = re.sub(r"^[-*・]\s*", "", ln)
        ln = re.sub(r"\*\*", "", ln)
        if ln.startswith("判定") or ln.startswith("根拠") or ln.startswith("×"):
            continue
        if len(ln) >= 8:
            return ln[:90]
    return fallback[:90] if fallback else (lines[0][:90] if lines else "")


def look_from(chunk: str) -> str:
    m = POINT.search(chunk or "")
    if m:
        t = re.sub(r"[「『」』\*]", "", m.group(1)).strip()
        return t[:40]
    qs = QUOTE.findall(chunk or "")
    return qs[0][:40] if qs else ""


def parse_legs_from_ai(ai: dict, maj_ch: dict[str, str | None]) -> list[dict]:
    body = sec(ai, "⑤") or sec(ai, "⑥") or ""
    parts = split_legs(body)
    # Also try whole sections joined if ⑤ didn't split
    if len(parts) < 2:
        parts = split_legs("\n".join((ai.get("sections") or {}).values()))
    choices = {k: ox(v) for k, v in (ai.get("choices") or {}).items()}
    labels = sorted(set(parts) | set(choices) | set(maj_ch), key=lambda x: (len(x), x))
    # Prefer kana legs if present
    kana = [x for x in labels if re.fullmatch(r"[ア-ン]", x)]
    if kana:
        labels = kana
    legs = []
    for lab in labels:
        chunk = parts.get(lab, "")
        j = JUDGE.search(chunk)
        mark = ox(j.group(1)) if j else ox(choices.get(lab) or (maj_ch.get(lab) or ""))
        if not mark:
            continue
        one = one_liner(chunk, fallback=f"肢{lab}は{'正しい' if mark == '○' else '誤り'}")
        # Wrap a short keyword in 【】 for the UI's <em> highlight
        if "【" not in one:
            am = re.search(
                r"(免訴|公訴棄却|間接正犯|共同正犯|背信的悪意者|確定判決|緊急避難|正当防衛)",
                one,
            )
            if am:
                one = one.replace(am.group(1), f"【{am.group(1)}】", 1)
        src = ""
        gm = re.search(r"根拠\s*[:：]\s*(.+)", chunk)
        if gm:
            src = re.sub(r"\*\*", "", gm.group(1)).strip()[:80]
        legs.append(
            {
                "l": lab,
                "ox": mark,
                "look": look_from(chunk),
                "one": one,
                "src": src,
                "warn": "",
            }
        )
    return legs


def build_axis(ai: dict, theme: str) -> dict:
    s1 = sec(ai, "①")
    s2 = sec(ai, "②")
    s7 = sec(ai, "⑦")
    lead = first_sentence(s1, 140) or (theme + "の軸を押さえる。")
    boxes = []
    # Pull checklist-like lines from ⑦
    steps = []
    for ln in (s7 or s1 or "").splitlines():
        ln = re.sub(r"^\s*\d+[\.\、\)]\s*", "", ln.strip())
        ln = re.sub(r"^[-*・]\s*", "", ln)
        ln = re.sub(r"\*\*", "", ln)
        if 8 <= len(ln) <= 80:
            steps.append(ln)
        if len(steps) >= 4:
            break
    if steps:
        rows = [[steps[i], steps[i + 1] if i + 1 < len(steps) else ""] for i in range(0, min(len(steps), 4), 2)]
        boxes.append({"q": "どう切るか", "rows": rows})
    elif s2.strip():
        # Collapse diagram into one box of key lines
        lines = []
        for ln in s2.splitlines():
            ln = re.sub(r"[│├└┌┐┘┴┬┤─━|/\\=`]", " ", ln)
            ln = re.sub(r"\s+", " ", ln).strip(" -")
            if 6 <= len(ln) <= 70 and not ln.startswith("```"):
                lines.append(ln)
            if len(lines) >= 4:
                break
        if lines:
            rows = [[lines[i], lines[i + 1] if i + 1 < len(lines) else ""] for i in range(0, min(len(lines), 4), 2)]
            boxes.append({"q": "見取り図", "rows": rows})
    if not boxes:
        boxes.append(
            {
                "q": "この問題の軸",
                "rows": [[theme or "争点", first_sentence(s1, 80) or "各社の①・②を対照する"]],
            }
        )
    note = first_sentence(sec(ai, "⑧"), 120)
    return {"lead": lead, "boxes": boxes, "note": note}


def build_traps(ai: dict) -> list[list[str]]:
    text = "\n".join([sec(ai, "⑧"), sec(ai, "⑥"), sec(ai, "⑦")])
    traps: list[list[str]] = []
    # 「AとB」 patterns
    for m in re.finditer(r"([^\n。]{2,24})\s*と\s*([^\n。]{2,24})", text):
        a, b = re.sub(r"\*\*", "", m.group(1)).strip(), re.sub(r"\*\*", "", m.group(2)).strip()
        if any(x in a + b for x in ("条", "判", "説", "免訴", "棄却", "正犯", "故意", "過失", "登記")):
            # surrounding sentence as tip
            start = max(0, m.start() - 0)
            tip = first_sentence(text[m.start() : m.start() + 160], 100)
            traps.append([f"{a} と {b}", tip or "混同しやすい。条文の箱で切り分ける。"])
        if len(traps) >= 4:
            break
    if not traps:
        tip = first_sentence(sec(ai, "⑧") or sec(ai, "⑥"), 100)
        if tip:
            traps.append(["取り違えやすい点", tip])
    return traps


def build_reqs(q: dict, ai: dict) -> list[list[str]]:
    arts = list(ai.get("articles") or [])
    if not arts:
        # union across AIs
        seen = []
        for a in ais(q):
            for x in q["ai"][a].get("articles") or []:
                if x not in seen:
                    seen.append(x)
        arts = seen
    s4 = sec(ai, "④")
    reqs = []
    for art in arts[:8]:
        # find a nearby explanation in ④
        scene, req = "", ""
        if s4 and art.replace("条", "")[:6] in s4.replace(" ", ""):
            # take a short window after the article mention
            idx = s4.find(art[:6]) if art[:6] in s4 else -1
            if idx < 0:
                for tok in re.findall(r"\d+条", art):
                    idx = s4.find(tok)
                    if idx >= 0:
                        break
            if idx >= 0:
                window = s4[idx : idx + 220]
                scene = first_sentence(window, 40)
                req = first_sentence(re.sub(r"^.+?\n", "", window, count=1), 80)
        if not scene:
            scene = "関連条文"
        if not req:
            req = art + "の要件・効果を各社④で確認"
        reqs.append([art, scene, req])
    return reqs


def build_next(ai: dict) -> str:
    s = sec(ai, "⑨") or sec(ai, "⑦") or sec(ai, "⑧")
    # Prefer numbered steps joined
    steps = []
    for ln in (s or "").splitlines():
        ln = re.sub(r"^\s*\d+[\.\、\)]\s*", "", ln.strip())
        ln = re.sub(r"^[-*・]\s*", "", ln)
        ln = re.sub(r"\*\*", "", ln)
        if 8 <= len(ln) <= 100 and "一撃" not in ln and not ln.startswith("#"):
            steps.append(ln)
        if len(steps) >= 3:
            break
    if steps:
        return "／".join(steps)[:200]
    return first_sentence(s, 160)


def build_flow(ai: dict) -> list[dict]:
    """論文用：③規範カードや本文から論点フローを粗く作る。"""
    body = sec(ai, "③") or sec(ai, "①")
    chunks = re.split(r"(?m)^(?:#{2,4}\s+|\*\*)", body)
    flow = []
    n = 0
    for ch in chunks:
        ch = ch.strip()
        if len(ch) < 20:
            continue
        n += 1
        title = first_sentence(ch, 40) or f"論点{n}"
        flow.append(
            {
                "n": title,
                "rule": first_sentence(ch, 120),
                "facts": [],
                "concl": "",
                "src": "",
                "warn": "",
            }
        )
        if n >= 5:
            break
    return flow


def is_ronbun(q: dict, day: str) -> bool:
    if "★論文" in (day or ""):
        return True
    if (q.get("sum") or {}).get("kind") == "ronbun":
        return True
    return False


def make_sum(q: dict, day: str) -> dict | None:
    R = ai_rank(q)
    if not R or not R["rank"]:
        return None
    src_ai_name = R["rank"][0]
    # Prefer AI that actually has ⑤ leg breakdown
    for a in R["rank"]:
        if len(split_legs(sec(q["ai"][a], "⑤"))) >= 2:
            src_ai_name = a
            break
    ai = q["ai"][src_ai_name]
    title_theme = (q.get("title") or "").split("　")[-1]
    title_theme = re.sub(r"【.*?】", "", title_theme).strip() or (q.get("id") or "本問")
    s1_theme = re.sub(
        r"(を聞いている|を問う|について).*$",
        "",
        first_sentence(sec(ai, "①"), 60),
    ).strip("。． 、")
    # Prefer short noun-ish themes from ①; otherwise keep the title slug
    if s1_theme and 4 <= len(s1_theme) <= 28 and "ので" not in s1_theme and "ます" not in s1_theme:
        theme = s1_theme
    else:
        theme = title_theme[:40]

    ans_raw = ai.get("answer") or ""
    # Prefer majority digit answer
    ans = R.get("maj_ans") or na(ans_raw) or ans_raw
    if isinstance(ans, str) and ans.isdigit() is False and na(ans_raw):
        ans = na(ans_raw) or ans
    answer_note = first_sentence(sec(ai, "③"), 80)

    made = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    zu = pick_zu(q, R["rank"])
    axis = build_axis(ai, theme)
    traps = build_traps(ai)
    reqs = build_reqs(q, ai)
    nxt = build_next(ai)

    if is_ronbun(q, day) or R.get("ronbun"):
        return {
            "kind": "ronbun",
            "theme": theme,
            "answer": ans if not str(ans).isdigit() else "",
            "answer_note": answer_note,
            "axis": axis,
            "flow": build_flow(ai),
            "traps": traps,
            "reqs": reqs,
            "must": [x for x in [first_sentence(sec(ai, "③"), 100), first_sentence(sec(ai, "⑧"), 80)] if x][:3],
            "next": nxt,
            "zu": zu,
            "made": made,
            "via": "extractive",
        }

    legs = parse_legs_from_ai(ai, R.get("maj_ch") or {})
    # Try other AIs if the top one lacked a ⑤ breakdown
    if len(legs) < 2:
        for a in R["rank"][1:]:
            alt = parse_legs_from_ai(q["ai"][a], R.get("maj_ch") or {})
            if len(alt) > len(legs):
                legs = alt
                src_ai_name = a
                ai = q["ai"][a]
            if len(legs) >= 2:
                break
    # Synthesize from maj_ch / own choices
    if not legs:
        chmap = dict(R.get("maj_ch") or {})
        if not chmap:
            for a in R["rank"]:
                for lb, mark in (q["ai"][a].get("choices") or {}).items():
                    chmap.setdefault(lb, mark)
        for lab, mark in sorted(chmap.items(), key=lambda x: (len(x[0]), x[0])):
            if not mark:
                continue
            legs.append(
                {
                    "l": lab,
                    "ox": ox(mark),
                    "look": "",
                    "one": f"肢{lab}は多数説で【{ox(mark)}】",
                    "src": f"軸：{src_ai_name}ほか多数",
                    "warn": "",
                }
            )
    # Last resort: pull ○× from answer text like 「2（ア・ウ）」
    if not legs and ans_raw:
        m = re.search(r"[（(]([ア-ン・､、,\s]+)[）)]", str(ans_raw))
        if m:
            goods = set(re.findall(r"[ア-ン]", m.group(1)))
            universe = list("アイウエオカ")
            for lab in universe:
                mark = "○" if lab in goods else "×"
                legs.append(
                    {
                        "l": lab,
                        "ox": mark,
                        "look": "",
                        "one": f"肢{lab}は正解組み合わせ上【{mark}】",
                        "src": f"軸：正解 {ans_raw}",
                        "warn": "",
                    }
                )
            last_o = max((i for i, L in enumerate(legs) if L["ox"] == "○"), default=-1)
            if last_o >= 0:
                legs = legs[: max(last_o + 1, 5)]

    return {
        "theme": theme,
        "answer": str(ans)[:20],
        "answer_note": answer_note,
        "axis": axis,
        "legs": legs,
        "traps": traps,
        "reqs": reqs,
        "next": nxt,
        "zu": zu,
        "made": made,
        "via": "extractive",
    }


def refresh_week(data_dir: str) -> None:
    path = os.path.join(data_dir, "week.json")
    if not os.path.isfile(path):
        return
    week = json.load(open(path, encoding="utf-8"))
    # index sums by day|id
    idx: dict[str, dict] = {}
    for f in glob.glob(os.path.join(data_dir, "2026-*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for day in d.get("days") or []:
            for q in day.get("qs") or []:
                S = q.get("sum") or {}
                idx[f"{day.get('day')}|{q.get('id')}"] = S
    changed = 0
    for r in week.get("rows") or []:
        S = idx.get(f"{r.get('day')}|{r.get('id')}") or {}
        if not S:
            continue
        new_sum = True
        new_theme = S.get("theme") or r.get("theme")
        new_lead = (S.get("axis") or {}).get("lead") or r.get("lead")
        new_ans = S.get("answer") or r.get("ans")
        new_traps = S.get("traps") or r.get("traps")
        if (
            r.get("sum") != new_sum
            or r.get("theme") != new_theme
            or r.get("lead") != new_lead
            or r.get("ans") != new_ans
            or r.get("traps") != new_traps
        ):
            r["sum"] = new_sum
            r["theme"] = new_theme
            r["lead"] = new_lead
            r["ans"] = new_ans
            r["traps"] = new_traps
            changed += 1
    if changed:
        json.dump(week, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"week.json: updated {changed} rows")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="欠落だけでなく extractive 済みも再生成")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--data", default=DATA)
    args = ap.parse_args()
    overwrite_llm = os.environ.get("QSUM_OVERWRITE_LLM") == "1"

    files = sorted(glob.glob(os.path.join(args.data, "2026-*.json")))
    filled = failed = kept = 0
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        dirty = False
        for day in d.get("days") or []:
            for q in day.get("qs") or []:
                S0 = q.get("sum") or {}
                is_ext = S0.get("via") == "extractive"
                is_llm = bool(S0) and not is_ext
                # LLM / hand-authored sums are preserved unless QSUM_OVERWRITE_LLM=1
                if is_llm and not overwrite_llm:
                    kept += 1
                    continue
                # Extractive: refresh only with --force; missing always filled
                if S0 and is_ext and not args.force:
                    kept += 1
                    continue
                if S0 and not is_ext and not overwrite_llm:
                    kept += 1
                    continue
                try:
                    S = make_sum(q, day.get("day") or "")
                except Exception as e:
                    failed += 1
                    print(f"FAIL {os.path.basename(f)} {q.get('id')}: {e}", file=sys.stderr)
                    continue
                if not S:
                    failed += 1
                    continue
                if args.dry_run:
                    filled += 1
                    continue
                q["sum"] = S
                dirty = True
                filled += 1
        if dirty and not args.dry_run:
            json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"wrote {os.path.basename(f)}")
    print(f"filled={filled} kept_existing={kept} failed={failed} dry_run={args.dry_run}")
    if not args.dry_run and filled:
        refresh_week(args.data)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    # Fix a small syntax slip in build_axis lead fallback (avoid broken f-string with JP quotes)
    sys.exit(main())

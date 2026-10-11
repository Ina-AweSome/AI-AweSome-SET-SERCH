#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_run.py — 予備試験「AI補完」配布＆回収エンジン（Chrome + Playwright）

1プロセスで完結:
  ① プロンプトを選ぶ → 問題文（クリップボード等）を差し込む
  ② 各サイトのタブに一括で貼付＆送信（配布）
  ③ あなたが全AIの生成完了を目視 → Enter
  ④ 各回答を読み取り、Obsidian ２）AI補完/{AI名}/ に保存（回収）
  ⑤ 配布開始〜回収完了までの所要時間を表示

専用プロファイル(bar-exam-ai-profile)の Chrome を「普通に」起動して操作する
（自動テスト扱いにならないので Google にもログインできる）。普段のChromeとは別物なので、
初回は各AIサイトへ「この窓の中で」ログインが要る（--login で一括で開ける）。
実行後も専用Chromeは開いたまま残り、次回はそのまま使う（閉じたければ ⌘Q）。

NotebookLM は問題ごとに「短答」「論文」を分けたノートブックを作る。
  名前は 例) 1011AI【短答】商法 Q32-Q35 株主総会決議の瑕疵
          / 1011AI【論文】商法 第3問 取締役の対第三者責任
  まず「1011AI【論文】」で新規作成して問題文を「コピーしたテキスト」のソースに入れ、
  後半（科目・問題番号・内容）は NotebookLM の回答末尾の【タイトル】行から付ける
  （その行は保存する回答からは除く。取れなければ --subject / --qid を使う）。
  画面が変わって自動で開けない/作れない時は、配布前の一時停止中に手で開いて Enter。
  短答/論文の判定はプロンプトのファイル名・見出し（「短答」を含めば短答、それ以外は論文）。
  --kind 短答 / --kind 論文 で上書きできる。
  data/notebooklm.json にURLを書くと、名前で探さずそのノートブックを常に使う（固定したい時だけ）。

使い方:
  python3 ai_run.py --login                 # 各AIを開くだけ（ログイン用・送信しない）
  python3 ai_run.py --check                  # ログイン状態だけ確認して閉じる
  python3 ai_run.py --pattern 1              # 問題文=クリップボード, パターン1で配布→回収
  python3 ai_run.py                          # パターンを対話選択
  python3 ai_run.py --subject 民訴法 --qid Q315   # 保存ファイル名に科目・問題番号
  python3 ai_run.py --sites Gemini,NotebookLM   # 一部サイトだけ
  python3 ai_run.py --kind 論文               # NotebookLM のノートブックを論文用に固定
  python3 ai_run.py --dry-run                # 送信せず、組み立てたプロンプトだけ表示
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 実Chrome(channel="chrome")で使う専用プロファイル。Google Drive同期外のローカル。
# 初回は通常のChromeでこのフォルダにログインしておく（AI初回ログイン.command）。
USER_DATA_DIR = Path("/Users/osamuinagaki/bar-exam-ai-profile")
PROMPT_DIR = HERE / "data" / "ai_prompts"
NOTEBOOKLM_CONFIG = HERE / "data" / "notebooklm.json"
NOTEBOOKLM_HOME = "https://notebooklm.google.com/"
OBSIDIAN_DAILY_DIR = Path(
    "/Users/osamuinagaki/Documents/ObsidianVault/Time based-司法試験予備試験"
) / "TimeBase" / "10_Daily Log"

# ── サイト定義 ─────────────────────────────────────────
# input: 入力欄の候補セレクタ（上から試す）
# send:  "enter" = 入力後Enterで送信 / それ以外はセレクタをクリック
# answer: 最新の回答テキストを含む要素の候補セレクタ（回収用）
# 自動化対象は Gemini・Copilot・NotebookLM。
# ChatGPT / Claude / Grok は各社が自動化ブラウザを弾く（Cloudflare・本人確認・未ログイン化）ため保留。
# 配布時にプロンプトをクリップボードへコピーするので、必要なら普段のChromeへ手動で貼り付ける。
SITES = {
    "Gemini": {
        "url": "https://gemini.google.com/app",
        "input": ["div.ql-editor[contenteditable='true']", "rich-textarea .ql-editor",
                  "div[contenteditable='true']"],
        "send": "enter",
        "answer": [".model-response-text", "message-content", ".markdown"],
    },
    "Copilot": {
        "url": "https://copilot.microsoft.com/",
        "input": ["textarea#userInput", "textarea", "div[contenteditable='true']"],
        "send": "enter",
        "answer": ["[data-content='ai-message']", ".ac-textBlock", ".prose"],
    },
    # NotebookLM: url は短答/論文で差し替える（notebook_url() 参照）。
    # セレクタは画面構成の変更で外れることがある。外れたら --check で入力欄の有無を確認。
    "NotebookLM": {
        "url": NOTEBOOKLM_HOME,
        "input": ["textarea.query-box-input", "query-box textarea",
                  "textarea[aria-label*='クエリ']", "textarea[aria-label*='query' i]",
                  "textarea"],
        "send": "enter",
        "answer": [".to-user-container .message-text-content",
                   "chat-message .message-text-content",
                   ".message-text-content", "chat-message"],
    },
}

# 回収テキストから各サイトの定型ゴミを除く
_BOILERPLATE = [
    "Copilot の発言", "ページ内で編集します", "Gemini の回答",
    "You said:", "ChatGPT said:",
    "メモに保存", "Save to note", "copy_all", "thumb_up", "thumb_down", "keep_pin",
]


def clean_answer(text: str) -> str:
    t = text.strip()
    for b in _BOILERPLATE:
        t = t.replace(b, "")
    return t.strip()

# 文字化け検知：置換文字や典型的な化けパターン
def looks_mojibake(text: str) -> bool:
    if not text:
        return False
    bad = text.count("�")            # replacement char
    if bad >= 3:
        return True
    # UTF-8をLatin-1で読んだ時の典型（Ã, Â, ã‚ などが多発）
    suspicious = sum(text.count(c) for c in ("Ã", "Â", "â€", "ã\x82", "ã\x83"))
    return suspicious >= 5


def read_clipboard() -> str:
    try:
        return subprocess.run(["pbpaste"], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except Exception:
        return ""


def write_clipboard(text: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=text, text=True, timeout=5)
        return True
    except Exception:
        return False


def load_patterns() -> list:
    files = sorted(PROMPT_DIR.glob("*.md"))
    out = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines()
                      if ln.strip().startswith("#")), f.stem)
        out.append({"file": f, "title": title, "body": text})
    return out


def choose_pattern(patterns: list, idx: int | None) -> dict:
    if idx is not None:
        if 1 <= idx <= len(patterns):
            return patterns[idx - 1]
        raise SystemExit(f"パターン番号 {idx} は範囲外（1〜{len(patterns)}）")
    print("=== プロンプト・パターン ===")
    for i, p in enumerate(patterns, 1):
        print(f"  {i}. {p['title']}")
    sel = input("番号を選択: ").strip()
    return patterns[int(sel) - 1]


def build_prompt(pattern_body: str, mondai: str) -> str:
    # 先頭の見出し行（# タイトル）は送信本文から落とす
    lines = pattern_body.splitlines()
    if lines and lines[0].strip().startswith("#"):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    if "{問題文}" in body:
        return body.replace("{問題文}", mondai)
    return body + "\n\n問題:\n" + mondai


# ── NotebookLM（短答用／論文用ノートブック）────────────────
KINDS = ("短答", "論文")


def detect_kind(pattern: dict | None) -> str:
    """プロンプトのファイル名・見出しから短答/論文を判定（「短答」を含めば短答）。"""
    if not pattern:
        return "短答"
    key = f"{pattern['file'].name} {pattern['title']}"
    return "短答" if "短答" in key else "論文"


def load_notebooklm_config() -> dict:
    try:
        raw = json.loads(NOTEBOOKLM_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: (raw.get(k) or "").strip() for k in KINDS}


def notebook_url(kind: str) -> str:
    """短答/論文のノートブックURL。未設定なら NotebookLM のトップ。"""
    return load_notebooklm_config().get(kind) or NOTEBOOKLM_HOME


def site_url(name: str, kind: str) -> str:
    if name == "NotebookLM":
        return notebook_url(kind)
    return SITES[name]["url"]


def notebook_title(kind: str, label: str = "", day: date | None = None) -> str:
    """ノートブック名。例: 1011AI【論文】商法 第3問 取締役の対第三者責任
    【】の後ろ（label）は NotebookLM の回答から付ける（TITLE_ASK 参照）。"""
    d = day or date.today()
    return f"{d:%m%d}AI【{kind}】{label}"


# ノートブック名の後半（科目・問題番号・内容）を NotebookLM 自身に付けさせる指示。
# 回答の最後の行から拾い、保存する回答からは取り除く。
TITLE_TAG = "【タイトル】"
TITLE_ASK = (f"\n\n最後に1行だけ「{TITLE_TAG}」に続けて、この問題の科目・問題番号・"
             "主要論点（15字以内）を半角スペース区切りで書いてください"
             "（例: {tag}商法 第3問 取締役の対第三者責任 / "
             "{tag}商法 Q32-Q35 株主総会決議の瑕疵）。"
             ).replace("{tag}", TITLE_TAG)


def split_title_label(text: str) -> tuple[str, str]:
    """回答末尾の【タイトル】行を取り出す。(本文, ラベル)。無ければラベルは空。"""
    lines = text.rstrip().splitlines()
    for i in range(len(lines) - 1, max(-1, len(lines) - 6), -1):
        ln = lines[i].strip().strip("*").strip()
        if ln.startswith(TITLE_TAG):
            label = ln[len(TITLE_TAG):].strip(" 　：:「」*")
            # 名前で困る記号を除き、空白は半角1つにそろえる
            for ch in '/\\:*?"<>|':
                label = label.replace(ch, "・" if ch in "/\\" else "")
            label = " ".join(label.replace("　", " ").split())
            body = "\n".join(lines[:i] + lines[i + 1:]).rstrip()
            return body, label[:40]
    return text, ""


def _first_visible(page, selectors):
    for sel in selectors:
        try:
            loc = page.locator(sel)
            for i in range(min(loc.count(), 20)):
                el = loc.nth(i)
                if el.is_visible():
                    return el
        except Exception:
            continue
    return None


def _wait_for(page, selectors, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        el = _first_visible(page, selectors)
        if el:
            return el
        time.sleep(0.5)
    return None


# NotebookLM の画面部品（候補セレクタ。画面変更で外れたら手動に切り替わる）
_NB_CREATE = ["button:has-text('新規作成')", "button:has-text('ノートブックを新規作成')",
              "button:has-text('Create new')", "button:has-text('New notebook')"]
_NB_PASTE = ["button:has-text('コピーしたテキスト')", "mat-chip:has-text('コピーしたテキスト')",
             "button:has-text('テキストを貼り付け')", "button:has-text('Copied text')",
             "mat-chip:has-text('Copied text')"]
_NB_PASTE_AREA = ["mat-dialog-container textarea", "[role='dialog'] textarea", "textarea"]
_NB_INSERT = ["button:has-text('挿入')", "button:has-text('Insert')"]
_NB_TITLE = ["input.title-input", "editable-project-title input",
             "input[aria-label*='タイトル']", "input[aria-label*='title' i]"]


def rename_notebook(page, title: str) -> bool:
    """開いているノートブックの名前を title に変える。"""
    t = _wait_for(page, _NB_TITLE, timeout=20)
    if not t:
        return False
    try:
        t.click()
        t.fill(title)
        t.press("Enter")
        return True
    except Exception:
        return False


def open_today_notebook(page, kind: str, mondai: str) -> tuple[bool, str]:
    """問題ごとのノートブックを用意する（短答・論文とも1回の実行で1冊）。
    名前がまだ「1011AI【短答】」「1011AI【論文】」のまま（後半未付与）のものがあれば再利用し、
    無ければ新規作成（問題文を「コピーしたテキスト」のソースとして追加）。
    後半（科目と問題番号）は回収時に回答から付ける。"""
    title = notebook_title(kind)
    pattern = "^\\s*" + title.replace("【", "\\【").replace("】", "\\】") + "\\s*$"
    # ① 後半未付与の作りかけノートブックを探す
    card = _wait_for(page, [f"text=/{pattern}/"], timeout=8)
    if card:
        try:
            name = card.inner_text().strip().splitlines()[0]
            card.click()
            page.wait_for_url("**/notebook/**", timeout=20000)
            return True, f"既存のノートブック「{name}」を開きました"
        except Exception as e:
            return False, f"ノートブック「{title}」を開けませんでした: {e}"
    # ② 無ければ作る
    steps = [("新規作成ボタン", _NB_CREATE), ("「コピーしたテキスト」", _NB_PASTE)]
    for label, sels in steps:
        el = _wait_for(page, sels)
        if not el:
            return False, f"{label}が見つからない（新規作成は手動でお願いします: {title}）"
        el.click()
        time.sleep(1.0)
    area = _wait_for(page, _NB_PASTE_AREA)
    if not area:
        return False, f"貼り付け欄が見つからない（手動で作成: {title}）"
    area.fill(mondai)
    ins = _wait_for(page, _NB_INSERT)
    if not ins:
        return False, f"挿入ボタンが見つからない（手動で作成: {title}）"
    ins.click()
    # 名前を付ける（失敗しても質問はできるので致命的ではない）
    if not rename_notebook(page, title):
        return True, f"新規作成しました（名前の変更は手動で: {title}）"
    return True, f"ノートブック「{title}」を新規作成しました（問題文をソースに追加）"


# ── Obsidian 保存 ─────────────────────────────────────
def find_ai_dir(subject: str | None, ai_name: str) -> Path:
    """当日の {日付}{科目}/２）AI補完/{AI名}/ を返す（無ければ作る）。"""
    today = date.today().isoformat()
    if subject:
        base = OBSIDIAN_DAILY_DIR / f"{today}{subject}"
    else:
        # 科目未指定なら当日の {日付}始まりフォルダを1つ探す
        cands = sorted(OBSIDIAN_DAILY_DIR.glob(f"{today}*"))
        cands = [c for c in cands if c.is_dir()]
        base = cands[0] if cands else (OBSIDIAN_DAILY_DIR / today)
    ai_dir = base / "２）AI補完" / ai_name
    ai_dir.mkdir(parents=True, exist_ok=True)
    return ai_dir


TEACHER = {
    "ChatGPT": "GPT先生", "Claude Sonnet": "claude先生", "Gemini": "gemini先生",
    "Grok": "Grok先生", "Copilot": "Copilot先生", "NotebookLM": "NotebookLM先生",
}


def save_answer(ai_name: str, text: str, subject: str | None, qid: str | None):
    ai_dir = find_ai_dir(subject, ai_name)
    base = TEACHER.get(ai_name, ai_name)
    stem = f"{base} {qid}" if qid else base
    path = ai_dir / f"{stem}.md"
    # 既存があれば連番
    n = 1
    while path.exists():
        path = ai_dir / f"{stem} {n}.md"
        n += 1
    header = f"<!-- {datetime.now():%Y-%m-%d %H:%M} {ai_name} 自動保存 -->\n\n"
    path.write_text(header + text.strip() + "\n", encoding="utf-8")
    return path


def fmt_elapsed(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m}分{s:02d}秒" if m else f"{s}秒"


# ── ブラウザ起動 ─────────────────────────────────────
# Playwright 自身に Chrome を起動させると、Mac ではキーチェーンを使わない設定
# （--use-mock-keychain）と自動化フラグで起動するため、
#   ・普通の Chrome で済ませたログイン（Cookie）が読めず毎回「未ログイン」になる
#   ・Google が「安全でないブラウザ」としてログイン自体を拒否する
# という問題が起きる。そこで専用プロファイルの Chrome を「普通に」起動し、
# デバッグ用ポート経由で操作だけ接続する（ログインもこの窓で普通にできる）。
CDP_PORT = 9223


def _port_open(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _profile_chrome_running() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", f"user-data-dir={USER_DATA_DIR}"],
                           capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip())
    except Exception:
        return False


def open_browser(p):
    """専用プロファイルの Chrome に接続する（無ければ普通に起動してから接続）。"""
    if not _port_open(CDP_PORT):
        if _profile_chrome_running():
            raise SystemExit(
                "専用Chromeが別の起動方法で開いたままです。その窓で ⌘Q するか、\n"
                "  pkill -f bar-exam-ai-profile\n"
                "を実行してから、もう一度実行してください。")
        # 前回の異常終了で残った「使用中」の印を消す（Chromeが動いていない時だけ）
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            try:
                (USER_DATA_DIR / name).unlink()
            except OSError:
                pass
        subprocess.Popen([
            "open", "-na", "Google Chrome", "--args",
            f"--user-data-dir={USER_DATA_DIR}",
            f"--remote-debugging-port={CDP_PORT}",
            "--no-first-run", "--no-default-browser-check",
        ])
        for _ in range(60):
            if _port_open(CDP_PORT):
                break
            time.sleep(0.5)
        else:
            raise SystemExit("Chromeの起動を確認できませんでした。もう一度実行してください。")
        time.sleep(1.0)
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    return browser, ctx


# ── ブラウザ操作 ─────────────────────────────────────
def find_input(page, selectors):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return el, sel
        except Exception:
            continue
    return None, None


def wait_input(page, selectors, timeout=15.0):
    """入力欄が描画されるまで待つ（Copilot などは読み込み後に遅れて出る）。"""
    end = time.monotonic() + timeout
    while True:
        el, sel = find_input(page, selectors)
        if el or time.monotonic() >= end:
            return el, sel
        time.sleep(0.5)


def login_status(name, page) -> str:
    """--check 用の表示。NotebookLM は一覧画面に入力欄が無いので、ログイン画面かどうかで判定。"""
    if name == "NotebookLM":
        url = page.url or ""
        if "accounts.google.com" in url:
            return "❌ 未ログイン（Googleのログイン画面）"
        if "notebooklm" in url:
            return "✅ ログイン済み（ノートブック一覧）"
        return f"❓ 判定できず（{url[:60]}）"
    el, _ = wait_input(page, SITES[name]["input"])
    return "✅ 入力欄あり" if el else "❌ 入力欄なし（未ログインの可能性）"


def distribute_one(page, site, prompt, dry_run=False):
    el, sel = find_input(page, site["input"])
    if not el:
        return False, "入力欄が見つからない（未ログイン/DOM変更の可能性）"
    if dry_run:
        return True, f"[dry-run] 入力欄OK({sel})・送信せず"
    try:
        el.click()
        time.sleep(0.3)
        page.keyboard.insert_text(prompt)   # 改行込みで一気に投入（Enter誤爆なし）
        time.sleep(0.3)
        if site["send"] == "enter":
            page.keyboard.press("Enter")
        else:
            btn = page.query_selector(site["send"])
            if btn:
                btn.click()
            else:
                page.keyboard.press("Enter")
        return True, f"送信OK({sel})"
    except Exception as e:
        return False, f"送信失敗: {e}"


def collect_one(page, site):
    for sel in site["answer"]:
        try:
            els = page.query_selector_all(sel)
            if els:
                text = clean_answer(els[-1].inner_text())
                if text:
                    warn = " ⚠️文字化けの疑い" if looks_mojibake(text) else ""
                    return text, f"取得OK({sel}, {len(text)}字){warn}"
        except Exception:
            continue
    return "", "回答要素が見つからない"


def main():
    ap = argparse.ArgumentParser(description="AI配布＆回収エンジン")
    ap.add_argument("--pattern", type=int, help="プロンプト番号（1始まり）")
    ap.add_argument("--text", help="問題文を直接指定（既定はクリップボード）")
    ap.add_argument("--subject", help="科目（保存フォルダ用）")
    ap.add_argument("--qid", help="問題番号（保存ファイル名用、例 Q315）")
    ap.add_argument("--sites", help="対象サイトをカンマ区切りで限定")
    ap.add_argument("--kind", choices=KINDS,
                    help="NotebookLM のノートブック（短答/論文）。既定はプロンプトから自動判定")
    ap.add_argument("--login", action="store_true", help="各サイトを開くだけ（ログイン用）")
    ap.add_argument("--check", action="store_true", help="ログイン状態だけ確認")
    ap.add_argument("--dry-run", action="store_true", help="送信せずプロンプトのみ表示")
    ap.add_argument("--no-wait", action="store_true", help="回収の待機をしない（配布のみ）")
    args = ap.parse_args()

    site_names = list(SITES.keys())
    if args.sites:
        want = [s.strip() for s in args.sites.split(",")]
        site_names = [s for s in site_names if s in want]
        if not site_names:
            raise SystemExit(f"対象サイトなし。指定可能: {list(SITES.keys())}")

    # --dry-run はブラウザ不要
    prompt = None
    pat = None
    if not (args.login or args.check):
        patterns = load_patterns()
        if not patterns:
            raise SystemExit(f"プロンプトが {PROMPT_DIR} にありません")
        pat = choose_pattern(patterns, args.pattern)
        mondai = args.text if args.text else read_clipboard()
        if not mondai:
            raise SystemExit("問題文が空です（--text かクリップボードで渡す）")
        prompt = build_prompt(pat["body"], mondai)
        # 保存用の科目・問題番号を対話入力（未指定かつ端末のとき）
        if sys.stdin.isatty():
            if not args.subject:
                args.subject = input("科目（空欄可, 例 民訴法）: ").strip() or None
            if not args.qid:
                args.qid = input("問題番号（空欄可, 例 Q315）: ").strip() or None
    kind = args.kind or detect_kind(pat)
    if pat:
        print(f"■ パターン: {pat['title']}")
        print(f"■ 問題文: {mondai[:60]}...")
    if "NotebookLM" in site_names:
        url = notebook_url(kind)
        where = (url if url != NOTEBOOKLM_HOME else
                 f"「{notebook_title(kind, '○○')}」を新規作成（○○=科目・問題番号・内容を回答から付与）")
        print(f"■ NotebookLM: {kind}用ノートブック  {where}")
    if pat and args.dry_run:
        print("\n===== 送信されるプロンプト =====\n")
        print(prompt)
        print("\n（--dry-run のため送信しません）")
        return

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx = open_browser(p)
        pages = {}

        def finish():
            # 開いたタブだけ閉じて接続を切る（専用Chromeは開いたまま＝次回はすぐ使える）
            for pg in pages.values():
                try:
                    pg.close()
                except Exception:
                    pass
            browser.close()

        for name in site_names:
            page = ctx.new_page()
            try:
                page.goto(site_url(name, kind), wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"[{name}] 遷移失敗: {e}")
            pages[name] = page
            time.sleep(1.0)

        if args.login:
            input("\n各サイトにログインしてください。完了したらEnterで閉じます...")
            finish()
            return

        if args.check:
            print("\n=== ログイン状態チェック ===")
            for name in site_names:
                print(f"  {name}: {login_status(name, pages[name])}")
            input("Enterで閉じます...")
            finish()
            return

        # ── NotebookLM：URL未設定なら、その日のノートブックを名前で開く／作る ──
        nb_title = notebook_title(kind)
        nb_auto = "NotebookLM" in site_names and notebook_url(kind) == NOTEBOOKLM_HOME
        if nb_auto:
            ok, msg = open_today_notebook(pages["NotebookLM"], kind, mondai)
            print(f"\n[NotebookLM] {msg}")

        # ── 配布前チェック：入力欄が出ていないサイトは手動対応を促す ──
        missing = [n for n in site_names
                   if not wait_input(pages[n], SITES[n]["input"])[0]]  # 描画待ち込み
        if missing:
            print("\n⚠️ 入力欄が出ていないサイト:", ", ".join(missing))
            print("  → その窓で手動対応してください（例: 未ログインならログイン）。")
            if "NotebookLM" in missing:
                print(f"  → NotebookLM はノートブック「{nb_title}」を開くか作ってください。")
            input("  対応が終わったら Enter を押すと配布します...")

        # ── 配布 ──
        t_start = time.monotonic()
        print(f"\n=== 配布（{datetime.now():%H:%M:%S} 開始）===")
        sent = set()
        # ノートブック名の後半（科目と問題番号）用の一行を回答末尾に付けてもらう
        ask_label = nb_auto
        for name in site_names:
            p_text = prompt + TITLE_ASK if (ask_label and name == "NotebookLM") else prompt
            ok, msg = distribute_one(pages[name], SITES[name], p_text)
            if ok:
                sent.add(name)
            print(f"  {name}: {msg}")

        # ── ChatGPT/Claude/Grok は保留（プロンプトをクリップボードにコピー）──
        if write_clipboard(prompt):
            print("\n📋 プロンプトをクリップボードにコピーしました。"
                  "ChatGPT/Claude/Grok を使いたい時は、普段のChrome(ログイン済み)を開いて "
                  "⌘V で貼り付けて送信してください（自動化保留中）。")

        if args.no_wait:
            print(f"\n⏱ 配布まで {fmt_elapsed(time.monotonic() - t_start)}")
            input("\n配布のみ。Enterで閉じます...")
            finish()
            return

        # ── 回収 ──
        input("\n★ 全AIの生成が終わったら Enter を押してください（回収します）...")
        t_wait = time.monotonic() - t_start
        print("\n=== 回収 ===")
        saved = 0
        for name in site_names:
            if name not in sent:
                # 送信できていない窓の回答は前回分の可能性があるので保存しない
                print(f"  {name}: 未送信のため回収しません")
                continue
            text, msg = collect_one(pages[name], SITES[name])
            if text and name == "NotebookLM" and ask_label:
                text, label = split_title_label(text)
                if not label and (args.subject or args.qid):
                    label = " ".join(x for x in (args.subject, args.qid) if x)
                if label:
                    new_title = notebook_title(kind, label)
                    done = rename_notebook(pages[name], new_title)
                    print(f"  NotebookLM: ノートブック名 → 「{new_title}」"
                          f"{'' if done else '（変更できず。手動でお願いします）'}")
                else:
                    print("  NotebookLM: 回答に【タイトル】行が無く、名前は付けられませんでした")
            if text:
                path = save_answer(name, text, args.subject, args.qid)
                saved += 1
                print(f"  {name}: {msg} → {path.name}")
            else:
                print(f"  {name}: {msg}")

        total = time.monotonic() - t_start
        print(f"\n⏱ 所要時間: 合計 {fmt_elapsed(total)}"
              f"（送信〜生成待ち {fmt_elapsed(t_wait)} / 回収 {fmt_elapsed(total - t_wait)}）"
              f"  保存 {saved}/{len(site_names)} 件")
        input("\n回収完了。Enterで閉じます...")
        finish()


if __name__ == "__main__":
    main()

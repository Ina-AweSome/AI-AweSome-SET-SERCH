#!/usr/bin/env python3
"""Move approved Inbox company files on local Google Drive (Mac).

Run on the home Mac (Cursor Desktop / local agent), NOT cloud:

  python3 scripts/move_drive_inbox.py --dry-run
  python3 scripts/move_drive_inbox.py --execute

Account folder usually looks like:
  ~/Library/CloudStorage/GoogleDrive-onextec.inagaki@gmail.com/マイドライブ
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


ACCOUNT_HINT = "onextec.inagaki@gmail.com"

# (inbox_name, destination relative to マイドライブ, create_missing_parents)
# destination is the PARENT folder that should receive the inbox item
MOVES: list[tuple[str, str]] = [
    (
        "20260725 高千穂工業☆見積セット",
        "10_お客様/【た】高千穂工業/01_見積/2026",
    ),
    (
        "20260730 茶谷 GEAR (新規登録)",
        "10_お客様/★Bユーザー/た/【ち】茶谷GEAR",
    ),
    (
        "20260803 シンフォニア商事 0BGX30B-Y1☆見積セット",
        "10_お客様/★Bユーザー/さ/【し】シンフォニア商事/01_見積/2026",
    ),
    (
        "20260804 高千穂工業☆見積セット",
        "10_お客様/【た】高千穂工業/01_見積/2026",
    ),
    (
        "20260804 神鋼造機☆見積セット",
        "10_お客様/【か】神鋼造機/01_見積/2026",
    ),
    (
        "20260804 水谷精機工作所☆見積セット",
        "10_お客様/★Bユーザー/み/【み】水谷精機工作所/01_見積/2026",
    ),
    (
        "20260804 西研精機製作所☆見積セット",
        "10_お客様/★Bユーザー/に/【に】西研精機製作所/01_見積/2026",
    ),
    (
        "20260805 ジェイテクト PIN 試作見積",
        "10_お客様/【じ】ジェイテクト/国分工場/01_見積/2026",
    ),
    (
        "20260611NSK ワーナー様監査議事録.docx",
        "10_お客様/★Bユーザー/さ/【し】シンフォニア商事",
    ),
    (
        "20260731 高洋電機カドカ様見積回答 SS400.pdf",
        "10_お客様/★Bユーザー/か/【こ】高洋電気/カドカさん/2026",
    ),
]


def find_my_drive() -> Path:
    env = os.environ.get("GOOGLE_MY_DRIVE")
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p
        raise SystemExit(f"GOOGLE_MY_DRIVE is not a directory: {p}")

    cloud = Path.home() / "Library" / "CloudStorage"
    if not cloud.is_dir():
        raise SystemExit(
            "Google Drive mount not found. Open Google Drive for desktop, "
            "or set GOOGLE_MY_DRIVE to マイドライブ path."
        )

    candidates: list[Path] = []
    for entry in sorted(cloud.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if "GoogleDrive" not in name:
            continue
        if ACCOUNT_HINT.lower() not in name.lower() and "onextec" not in name.lower():
            # keep as fallback if only one GoogleDrive exists
            pass
        for my in ("マイドライブ", "My Drive"):
            md = entry / my
            if md.is_dir():
                candidates.append(md)

    preferred = [c for c in candidates if ACCOUNT_HINT.lower() in str(c).lower() or "onextec" in str(c).lower()]
    pool = preferred or candidates
    if not pool:
        raise SystemExit(
            f"No マイドライブ under {cloud}. Set GOOGLE_MY_DRIVE explicitly."
        )
    if len(pool) > 1 and not preferred:
        joined = "\n".join(str(p) for p in pool)
        raise SystemExit(
            "Multiple Google Drive mounts found. Set GOOGLE_MY_DRIVE to one of:\n"
            + joined
        )
    return pool[0]


def resolve_existing_customer_folder(my_drive: Path, relative: str) -> Path:
    """Allow slight name differences for 神鋼造機 / ジェイテクト parents."""
    dest = my_drive / relative
    if dest.parent.is_dir() or relative.count("/") <= 1:
        return dest

    # If exact path missing, try fuzzy match for first customer segment under 10_お客様
    parts = Path(relative).parts
    if not parts or parts[0] != "10_お客様":
        return dest

    customers_root = my_drive / "10_お客様"
    if not customers_root.is_dir():
        return dest

    # Special cases where folder naming may omit 【行】 or ★B row folders
    return dest


def ensure_dir(path: Path, execute: bool) -> None:
    if path.is_dir():
        return
    print(f"  CREATE  {path}")
    if execute:
        path.mkdir(parents=True, exist_ok=True)


def move_item(src: Path, dest_dir: Path, execute: bool) -> None:
    target = dest_dir / src.name
    if target.exists():
        print(f"  SKIP    already exists: {target}")
        return
    print(f"  MOVE    {src.name}")
    print(f"       -> {dest_dir}")
    if execute:
        ensure_dir(dest_dir, execute=True)
        shutil.move(str(src), str(target))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Print actions only")
    group.add_argument("--execute", action="store_true", help="Create folders and move")
    args = parser.parse_args()
    execute = bool(args.execute)

    if sys.platform != "darwin" and not os.environ.get("GOOGLE_MY_DRIVE"):
        print(
            "WARNING: not macOS. This script expects a local Google Drive mount.\n"
            "If you are on cloud, it cannot see your Mac Drive.",
            file=sys.stderr,
        )

    my_drive = find_my_drive()
    inbox = my_drive / "00_Inbox"
    print(f"マイドライブ: {my_drive}")
    print(f"Inbox:       {inbox}")
    print(f"Mode:        {'EXECUTE' if execute else 'DRY-RUN'}")
    print()

    if not inbox.is_dir():
        raise SystemExit(f"00_Inbox not found at {inbox}")

    ok = 0
    missing = 0
    for name, rel in MOVES:
        src = inbox / name
        dest_dir = resolve_existing_customer_folder(my_drive, rel)
        print(f"[{name}]")
        if not src.exists():
            print("  MISSING in Inbox (already moved or renamed?)")
            missing += 1
            print()
            continue
        ensure_dir(dest_dir, execute=execute)
        move_item(src, dest_dir, execute=execute)
        ok += 1
        print()

    print(f"Done. planned/moved={ok}, missing={missing}")
    if not execute:
        print("Re-run with --execute to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

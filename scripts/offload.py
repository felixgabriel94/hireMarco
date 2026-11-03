#!/usr/bin/env python3
"""Marco offloads a camera card into the day's device folder, verified.

  uv run python scripts/offload.py [CARD] --day "/Volumes/LaCie/hireMarco Hackathon/13-footage/2026-11-03" [--device sony]

Without CARD, every mounted volume that looks like a camera card is offered.
The device folder is guessed from the card's layout (Sony, GoPro, iPhone, glasses) unless --device is given.
Every file is copied once (same name and size = already there), then read back and compared by SHA-256.
The card is never written to or erased. A log line per file goes to <day>/<device>/offload.jsonl.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

MEDIA = {".mov", ".mp4", ".m4v", ".mxf", ".mts", ".wav", ".jpg", ".jpeg", ".heic", ".dng", ".arw", ".xml", ".thm", ".lrv"}


def guess_device(card: Path) -> str | None:
    if (card / "PRIVATE" / "M4ROOT").exists() or (card / "PRIVATE" / "AVCHD").exists():
        return "a7r3"
    dcim = card / "DCIM"
    if dcim.exists():
        names = [p.name.upper() for p in dcim.iterdir() if p.is_dir()]
        if any("GOPRO" in n for n in names):
            return "gopro"
        if any("APPLE" in n for n in names):
            return "iphone"
        if any("MSDCF" in n for n in names):
            return "a7r3"
    return None


def candidates() -> list[Path]:
    out = []
    for v in sorted(Path("/Volumes").iterdir()) if Path("/Volumes").exists() else []:
        if v.name in ("Macintosh HD", "LaCie") or v.name.startswith("."):
            continue
        if (v / "DCIM").exists() or (v / "PRIVATE").exists():
            out.append(v)
    return out


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("card", nargs="?", type=Path)
    ap.add_argument("--day", type=Path, required=True, help="the day folder, e.g. .../13-footage/2026-11-03")
    ap.add_argument("--device", help="device folder name (default: guessed from the card)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    card = args.card
    if card is None:
        found = candidates()
        if not found:
            print("no camera card mounted (looked for DCIM or PRIVATE on /Volumes)", file=sys.stderr)
            return 2
        if len(found) > 1:
            print("several cards mounted, name one: " + ", ".join(str(f) for f in found), file=sys.stderr)
            return 2
        card = found[0]
    device = args.device or guess_device(card)
    if not device:
        print(f"cannot tell which camera {card} is from; pass --device", file=sys.stderr)
        return 2
    dest = args.day / device
    files = sorted(p for p in card.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA
                   and not p.name.startswith("._") and ".Trashes" not in p.parts)
    if not files:
        print(f"no media on {card}", file=sys.stderr)
        return 1
    total = sum(p.stat().st_size for p in files)
    print(f"{card} -> {dest}: {len(files)} files, {total / 1e9:.2f} GB")
    if args.dry_run:
        for p in files[:20]:
            print("  ", p.relative_to(card))
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(dest).free
    if free < total * 1.05:
        print(f"not enough room on {dest} ({free / 1e9:.1f} GB free, need {total / 1e9:.1f} GB)", file=sys.stderr)
        return 1
    log = open(dest / "offload.jsonl", "a")
    copied = skipped = bad = 0
    t_start = dt.datetime.now().astimezone()
    for p in files:
        target = dest / p.name
        if target.exists() and target.stat().st_size == p.stat().st_size:
            skipped += 1
            continue
        if target.exists():  # same name, different size: keep both
            target = dest / f"{p.stem}_{p.stat().st_size}{p.suffix}"
        tmp = target.with_name(target.name + ".part")
        shutil.copy2(p, tmp)
        want, got = sha256(p), sha256(tmp)
        if want != got:
            tmp.unlink(missing_ok=True)
            bad += 1
            print(f"  MISMATCH {p.name}, copy discarded", file=sys.stderr)
            continue
        tmp.rename(target)
        copied += 1
        log.write(json.dumps({"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "card": str(card),
                              "src": str(p.relative_to(card)), "dst": str(target), "bytes": p.stat().st_size,
                              "sha256": want}) + "\n")
        log.flush()
        print(f"  ok {p.name} ({p.stat().st_size / 1e6:.0f} MB)")
    took = (dt.datetime.now().astimezone() - t_start).total_seconds()
    verdict = "safe to format" if bad == 0 else f"{bad} files did not verify, do NOT format"
    print(f"Card copied: {copied} new, {skipped} already there, {bad} failed, {took:.0f} s. {verdict}.")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

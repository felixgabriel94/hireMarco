#!/usr/bin/env python3
"""Marco copies every camera card to the LaCie as soon as it is plugged in.

  uv run python scripts/card_watch.py --footage "/Volumes/LaCie/hireMarco Hackathon/13-footage"            # watch forever
  uv run python scripts/card_watch.py --footage "/Volumes/LaCie/hireMarco Hackathon/13-footage" --once     # one sweep (launchd)

Every few seconds the watcher looks at /Volumes for a card (a volume with DCIM or PRIVATE on it). A new card is
handed to scripts/offload.py, which copies every file into <footage>/<today>/<device>/<card>-<time>/ and verifies
each copy by SHA-256. The device folder is guessed from the card's layout (Sony, GoPro, iPhone); a card it cannot
place is reported, not guessed. When the copy ends the Owner gets a macOS notification and a line in
<footage>/cards.log, and the card is left untouched: nothing is ever formatted or deleted. The same card plugged
in twice is not copied twice; a card that failed is tried again on the next plug-in.
The watcher never touches the shared repo, the trace, or WhatsApp.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import offload  # noqa: E402

STATE = Path(os.environ.get("HIREMARCO_STATE", Path.home() / ".local" / "state" / "hiremarco")) / "cards"


def card_key(card: Path) -> str:
    """One id per plug-in: the volume name plus the time it was mounted."""
    try:
        mounted = int(card.stat().st_ctime)
    except OSError:
        mounted = 0
    return f"{card.name}-{mounted}"


def notify(title: str, text: str) -> None:
    if sys.platform != "darwin":
        return
    script = f'display notification "{text}" with title "{title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def log_line(footage: Path, text: str) -> None:
    stamp = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    with open(footage / "cards.log", "a") as f:
        f.write(f"{stamp}  {text}\n")


def today_folder(footage: Path) -> Path:
    return footage / dt.datetime.now().astimezone().strftime("%Y-%m-%d")


def handle(card: Path, footage: Path, dry_run: bool = False) -> str:
    """Copy one card. Returns a one-line verdict for the Owner."""
    key = card_key(card)
    STATE.mkdir(parents=True, exist_ok=True)
    done = STATE / f"{key}.done"
    busy = STATE / f"{key}.busy"
    if done.exists():
        return ""
    if busy.exists():
        try:
            pid = int(busy.read_text().strip() or 0)
        except ValueError:
            pid = 0
        if pid and pid_alive(pid):
            return ""
        busy.unlink(missing_ok=True)
    device = offload.guess_device(card)
    if not device:
        verdict = (f"Card {card.name}: cannot tell which camera it is from. Run by hand: "
                   f"uv run python scripts/offload.py \"{card}\" --day \"{today_folder(footage)}\" --device <name>")
        done.write_text("unknown device\n")
        return verdict
    day = today_folder(footage)
    busy.write_text(f"{os.getpid()}\n")
    try:
        argv = [str(card), "--day", str(day), "--device", device] + (["--dry-run"] if dry_run else [])
        notify("Marco", f"Copying the {device} card {card.name} to the LaCie")
        log_line(footage, f"start {card.name} -> {day / device}")
        proc = subprocess.run([sys.executable, str(HERE / "offload.py")] + argv, capture_output=True, text=True)
        lines = [ln for ln in (proc.stdout + "\n" + proc.stderr).splitlines() if ln.strip()]
        summary = lines[-1] if lines else "no output"
        if proc.returncode == 0:
            if not dry_run:
                done.write_text(summary + "\n")
            return summary
        return f"Card {card.name} ({device}) did not finish: {summary}. Keep the card and plug it in again."
    finally:
        busy.unlink(missing_ok=True)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def line_up(footage: Path, edit: Path, extra: list[str]) -> str:
    """Run the line-up on today's folder after a card lands; the Final Cut file goes under <edit>/auto-<HHMM>/."""
    day = today_folder(footage)
    out = edit / day.name / ("auto-" + dt.datetime.now().astimezone().strftime("%H%M"))
    cmd = [sys.executable, str(HERE / "assistant_editor.py"), str(day), "--out", str(out)] + extra
    proc = subprocess.run(cmd, capture_output=True, text=True)
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()][-1:] or ["no output"]
    if proc.returncode == 0:
        return f"Line-up ready: {out} ({tail[0]})"
    err = (proc.stderr.strip().splitlines() or ["no error text"])[-1]
    return f"Line-up failed on {day}: {err}"


def sweep(footage: Path, dry_run: bool = False, edit: Path | None = None, extra: list[str] | None = None) -> list[str]:
    out = []
    landed = False
    for card in offload.candidates():
        verdict = handle(card, footage, dry_run)
        if verdict:
            log_line(footage, verdict)
            notify("Marco", verdict[:200])
            print(verdict, flush=True)
            out.append(verdict)
            landed = landed or verdict.startswith("Card ") and "copied" in verdict and "did not finish" not in verdict
    if landed and edit and not dry_run:
        verdict = line_up(footage, edit, extra or [])
        log_line(footage, verdict)
        notify("Marco", verdict[:200])
        print(verdict, flush=True)
        out.append(verdict)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--footage", type=Path, required=True, help="the 13-footage folder on the LaCie")
    ap.add_argument("--once", action="store_true", help="one sweep, then exit (for launchd WatchPaths)")
    ap.add_argument("--every", type=float, default=5.0, help="seconds between looks when watching")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--edit", type=Path, help="12-edit/marco folder: run the line-up on today's folder after each card")
    ap.add_argument("--anchor", help="passed to the line-up (default audio-apollo)", default="audio-apollo")
    ap.add_argument("--events", type=Path, help="Marco's events.jsonl, passed to the line-up")
    args = ap.parse_args(argv)
    extra = ["--anchor", args.anchor] + (["--events", str(args.events)] if args.events else [])
    if not args.footage.exists():
        print(f"{args.footage} is not mounted; is the LaCie plugged in?", file=sys.stderr)
        return 2
    if args.once:
        sweep(args.footage, args.dry_run, args.edit, extra)
        return 0
    print(f"watching /Volumes for camera cards, copying into {args.footage}", flush=True)
    while True:
        if not args.footage.exists():
            print("LaCie went away; waiting", flush=True)
        else:
            try:
                sweep(args.footage, args.dry_run, args.edit, extra)
            except Exception as e:  # keep watching; the Owner hears about it in the log
                log_line(args.footage, f"watcher error: {e!r}")
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())

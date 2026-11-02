"""One plug-in's license, read off its own window in Logic: the last word on ownership.

The engine's list and the Control Panel are the first two lines; when they
disagree, or an authorization just landed while the engine kept running
(2026-11-02: a demo started and authorized, the engine's list still saying
"Demo not started"), the plug-in goes on the output strip for a moment, its
window is read, it comes off again, and the ledger carries what the window
said. Nothing else on the strip is touched.
"""

from __future__ import annotations

from collections.abc import Callable


def check(name: str, strip, look: Callable[[], object], mark: Callable[[str, str, str], None],
          log: Callable[[str], None] = print) -> str:
    """Insert ``name``, read its face, take it off, mark the ledger: returns the status written."""
    from collections import Counter

    from hiremarco.studio.stereo_out import same_plugin

    before = strip.read()
    seen: list = []
    after = strip.insert(name, look=lambda: seen.append(look()))
    # the one row that is new: the strip's rows move when an insert lands (2026-11-02: a read by position took
    # every insert off), so the new one is found by name count, the last row of a name that has one more than before
    counts_before = Counter(i.name for i in before.inserts)
    counts_after = Counter(i.name for i in after.inserts)
    grown = [n for n in counts_after if counts_after[n] > counts_before.get(n, 0) and same_plugin(name, n)]
    new = [i for i in sorted(after.inserts, key=lambda i: i.y) if i.name == grown[0]][-1:] if grown else []
    face = seen[0] if seen else None
    try:
        if face is None:
            status, why = "unknown", "its face could not be read on the strip; nothing changed in the ledger"
            log(f"   {name}: {why}")
            return status
        notice = (face.notice or "").strip()
        words = notice.lower()
        if any(w in words for w in ("start demo", "buy", "expired", "not active", "activate", "trial ended")):
            status, why = "not_owned", f"its window shows {notice} (read on the strip)"
        elif "demo" in words or "trial" in words or "days" in words:
            # an active demo reads as a notice to the eye but is a license for its days (2026-11-02: "DEMO ACTIVE - 14 DAYS")
            status, why = "demo", f"its window shows {notice} (read on the strip)"
        elif not face.licensed:
            status, why = "not_owned", f"its window shows {notice or 'a license notice'} (read on the strip)"
        else:
            status, why = "owned", "its window shows no license notice (read on the strip)"
        mark(name, status, why)
        log(f"   {name}: {status}; {why}")
        return status
    finally:
        if not new:
            log(f"   {name}: no new row found on the strip to take off; the strip is left as it is")
        for insert in new[:1]:   # one hand, one insert: never more than the one it added
            try:
                strip.remove(insert.name, insert.y)
                log(f"   {insert.name} taken off the strip again")
            except Exception as exc:   # noqa: BLE001
                log(f"   {insert.name} could not be taken off: {type(exc).__name__}: {str(exc)[-120:]}")
        try:
            strip.close_windows()
        except Exception:   # noqa: BLE001
            pass

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
    before = strip.read()
    seen: list = []
    after = strip.insert(name, look=lambda: seen.append(look()))
    new = [i for i in after.inserts if not any(abs(i.y - b.y) < 4 and i.name == b.name for b in before.inserts)]
    face = seen[0] if seen else None
    try:
        if face is None:
            status, why = "unknown", "its face could not be read on the strip; nothing changed in the ledger"
            log(f"   {name}: {why}")
            return status
        notice = (face.notice or "").strip()
        if not face.licensed:
            status, why = "not_owned", f"its window shows {notice or 'a license notice'} (read on the strip)"
        elif "demo" in notice.lower() or "trial" in notice.lower():
            status, why = "demo", f"its window shows {notice} (read on the strip)"
        else:
            status, why = "owned", "its window shows no license notice (read on the strip)"
        mark(name, status, why)
        log(f"   {name}: {status}; {why}")
        return status
    finally:
        for insert in new:
            try:
                strip.remove(insert.name, insert.y)
                log(f"   {insert.name} taken off the strip again")
            except Exception as exc:   # noqa: BLE001
                log(f"   {insert.name} could not be taken off: {type(exc).__name__}: {str(exc)[-120:]}")
        try:
            strip.close_windows()
        except Exception:   # noqa: BLE001
            pass

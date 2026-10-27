"""The job log: one JSON line per model call or job, with its cost.

Default path ``~/.local/state/hiremarco/jobs.jsonl`` (``HIREMARCO_STATE``
overrides the folder). The log is append-only; a correction is a new row.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from hiremarco.config import STATE_DIR


@dataclass
class JobRow:
    job: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    ok: bool = True
    note: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"))


class JobLog:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else STATE_DIR / "jobs.jsonl"

    def append(self, row: JobRow) -> JobRow:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
        return row

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def total_usd(self, day: str | None = None) -> float:
        """Spend in USD, all time or for one local date ``YYYY-MM-DD``."""
        rows = self.rows()
        if day:
            rows = [r for r in rows if r["ts"].startswith(day)]
        return round(sum(r.get("cost_usd", 0.0) for r in rows), 6)

    def summary(self) -> str:
        rows = self.rows()
        today = time.strftime("%Y-%m-%d")
        return (
            f"{len(rows)} jobs logged at {self.path}; "
            f"today {self.total_usd(today):.4f} USD; all time {self.total_usd():.4f} USD"
        )

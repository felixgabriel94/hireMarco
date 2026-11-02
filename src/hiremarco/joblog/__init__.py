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
        self.stream(row)
        return row

    def stream(self, row: JobRow) -> None:
        """The same call as one line of Marco's running log: the model, the job in plain words, the seconds."""
        from hiremarco import stream

        words = row.job.replace("_", " ").replace("-", " ")
        if row.note:
            words += f": {row.note}"
        elif not row.ok:
            words += ": failed"
        try:
            stream.say(row.model, words, row.duration_ms / 1000 if row.duration_ms else None,
                       at=self.path.with_name(stream.NAME) if self.path.name != "jobs.jsonl" else None)
        except OSError:
            pass

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def total_usd(self, day: str | None = None, job: str | None = None) -> float:
        """Spend in USD, all time or for one local date ``YYYY-MM-DD``, for every job or just the one named."""
        rows = self.rows()
        if day:
            rows = [r for r in rows if r["ts"].startswith(day)]
        if job:
            rows = [r for r in rows if r.get("job") == job]
        return round(sum(r.get("cost_usd", 0.0) for r in rows), 6)

    def summary(self) -> str:
        rows = self.rows()
        today = time.strftime("%Y-%m-%d")
        return (
            f"{len(rows)} jobs logged at {self.path}; "
            f"today {self.total_usd(today):.4f} USD; all time {self.total_usd():.4f} USD"
        )

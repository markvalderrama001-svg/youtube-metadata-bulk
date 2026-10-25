"""Timestamped CSV change log: one row per video touched, written as it happens.

The log is the journal for the batch and doubles as the undo file: it keeps
the full before and after title and description of every update, so
`ytbulk undo <log.csv>` can put each video back exactly as it was.
"""
from __future__ import annotations

import csv
from pathlib import Path

# Review columns first (what a human reads), then the full text undo needs.
FIELDS = [
    "video_id", "status", "old_title", "new_title", "old_desc_opening", "new_desc_opening",
    "updated_at", "action", "rule", "run_id", "old_description", "new_description",
]

# status values
PLANNED = "planned"          # dry run: would be written
UPDATED = "updated"          # written to YouTube (the only status undo acts on)
DEFERRED = "deferred_quota"  # left for the next run: today's quota budget is spent
FAILED = "failed"            # API refused; nothing changed
SKIPPED = "skipped"          # guard refused before any API call (reason in `rule`)


class ChangeLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.path.open("w", newline="", encoding="utf-8")
        self._w = csv.DictWriter(self._f, fieldnames=FIELDS)
        self._w.writeheader()
        self._f.flush()
        self.rows = 0

    def write(self, row: dict) -> None:
        self._w.writerow({k: row.get(k, "") for k in FIELDS})
        self._f.flush()  # a crash mid-batch still leaves every completed row on disk
        self.rows += 1

    def close(self) -> None:
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_log(path: str | Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    missing = [c for c in ("video_id", "status", "old_title", "new_title", "old_description", "new_description")
               if rows and c not in rows[0]]
    if missing:
        raise ValueError(f"{path} is not a ytbulk change log (missing columns: {', '.join(missing)})")
    return rows

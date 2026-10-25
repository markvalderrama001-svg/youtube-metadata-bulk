"""Quota budgeting for the YouTube Data API v3.

Every API call is charged against a daily budget *before* it is made. A call
that would push usage past the limit raises QuotaExceeded instead of being
sent, so a run stops cleanly before the API ever refuses it.

Default costs (YouTube Data API v3 quota table):
    channels.list / playlistItems.list / videos.list  =  1 unit per call
    videos.update                                       = 50 units per call
    daily limit                                         = 10,000 units
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

DEFAULT_COSTS = {"list": 1, "update": 50}


class QuotaExceeded(RuntimeError):
    """Raised before a call that would exceed the daily budget."""


@dataclass
class QuotaMeter:
    daily_limit: int = 10_000
    used: int = 0  # units already spent today (other tools, earlier runs)
    reserve: int = 0  # units deliberately left untouched for other work
    costs: dict = field(default_factory=lambda: dict(DEFAULT_COSTS))
    calls: dict = field(default_factory=dict)

    @property
    def ceiling(self) -> int:
        return self.daily_limit - self.reserve

    @property
    def remaining(self) -> int:
        return max(0, self.ceiling - self.used)

    def cost(self, op: str) -> int:
        return self.costs[op]

    def can_afford(self, op: str, n: int = 1) -> bool:
        return self.used + self.cost(op) * n <= self.ceiling

    def charge(self, op: str) -> int:
        c = self.cost(op)
        if self.used + c > self.ceiling:
            raise QuotaExceeded(
                f"{op} costs {c} units; {self.used:,} of {self.ceiling:,} already used "
                f"({self.remaining:,} left). Stopping before the API refuses the call."
            )
        self.used += c
        self.calls[op] = self.calls.get(op, 0) + 1
        return c

    def affordable_updates(self, verify: bool = True) -> int:
        """How many videos.update calls fit in what is left, keeping enough
        list units to re-read and verify every updated video (1 per 50 ids)."""
        n = self.remaining // self.cost("update")
        while n > 0:
            verify_cost = math.ceil(n / 50) * self.cost("list") if verify else 0
            if n * self.cost("update") + verify_cost <= self.remaining:
                return n
            n -= 1
        return 0

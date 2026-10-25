"""Offline end-to-end demo against the in-memory mock API (synthetic Demo Channel).

    1 scan      read the channel, find repeated title formulas and boilerplate
    2 plan      dry run: full diff + quota estimate, nothing written
    3 apply     day 1, with only 300 units of quota left: 5 written, rest deferred
              day 2: the deferred videos are picked up
    4 rerun     same rules again: nothing to do (idempotent)
    5 undo      reverse day 2 from its change log; a video hand-edited since is left alone
    6 sponsor   insert the sponsor block above timestamps; marker + 5,000-byte guards
"""
from __future__ import annotations

import contextlib
import io
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import changelog as cl
from . import demo_data
from .client import YouTubeClient
from .engine import bold, cyan, dim, execute, green, plan_rules, plan_sponsor, plan_undo, scan_report
from .mock import MockYouTube
from .quota import QuotaMeter
from .rules import load_config

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = ["scan", "plan", "apply", "rerun", "undo", "sponsor"]


def _clock(day: int, hour: int = 14):
    t = datetime(2026, 10, 19 + day, hour, 0, 0, tzinfo=timezone.utc)
    return lambda: t


def _header(n: int, text: str) -> None:
    print("\n" + bold(cyan(f"=== {n}. {text} ")) + cyan("=" * max(0, 66 - len(text))))


def run_demo(sections: list[str] | None = None, out_dir: Path | None = None,
             config: Path | None = None) -> dict:
    wanted = set(sections or SECTIONS)
    out_dir = Path(out_dir or ROOT / "output" / "demo")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    cfg = load_config(config or ROOT / "config" / "rules.example.yaml")
    api = MockYouTube(demo_data.CHANNEL_TITLE, demo_data.CHANNEL_ID, demo_data.VIDEOS, page_size=10)
    results: dict = {"api": api}

    @contextlib.contextmanager
    def section(name):
        if name in wanted:
            yield
        else:
            with contextlib.redirect_stdout(io.StringIO()):
                yield

    def client_for_day(used: int = 0) -> YouTubeClient:
        api.new_day()
        api.units_used = used  # other tools sharing the project already spent this today
        return YouTubeClient(api, QuotaMeter(daily_limit=10_000, used=used))

    # Day 1: another tool in the same Google Cloud project has used 9,700 units.
    yt = client_for_day(used=9_700)
    with section("scan"):
        _header(1, "Scan the channel (list calls only, 1 unit each)")
        before = yt.meter.used
        channel, videos = yt.scan()
        scan_report(channel, videos, cfg, yt.meter.used - before)
    with section("plan"):
        _header(2, "Dry run: preview every change before anything is written")
        changes, skips = plan_rules(videos, cfg)
        results["plan"] = execute(yt, changes, skips, apply=False, out_dir=out_dir, label="demo_day1", clock=_clock(1, 13))
        print(dim(f"  mock API writes so far: {len(api.updates)}"))
    with section("apply"):
        _header(3, "Apply, day 1: 300 units left today -> write what fits, defer the rest")
        results["day1"] = execute(yt, changes, skips, apply=True, out_dir=out_dir, label="demo_day1", clock=_clock(1))

        _header(3, "Apply, day 2: fresh quota, re-scan, pick up the deferred videos")
        yt = client_for_day()
        _, videos = yt.scan()
        changes, skips = plan_rules(videos, cfg)
        results["day2"] = execute(yt, changes, skips, apply=True, out_dir=out_dir, label="demo_day2", clock=_clock(2))
    with section("rerun"):
        _header(4, "Re-run the same rules: idempotent, nothing left to change")
        _, videos = yt.scan()
        changes, skips = plan_rules(videos, cfg)
        print(f"  proposed changes: {green(str(len(changes)))}   guard skips (unchanged): {len(skips)}")
        print(f"  quota used for the check: {dim('list calls only')}")
        results["rerun_changes"] = len(changes)
    with section("undo"):
        _header(5, "Undo day 2 from its change log (dry run first)")
        log_path = results["day2"].log_path
        api.edit_in_studio("demoVid0007", title="Accruals Explained: The Entry Everyone Gets Wrong")
        print(dim("  (meanwhile the creator retitled demoVid0007 by hand in YouTube Studio)"))
        rows = cl.read_log(log_path)
        u_changes, u_skips = plan_undo(yt, rows)
        execute(yt, u_changes, u_skips, apply=False, out_dir=out_dir, label="demo_undo", clock=_clock(2, 16))
        print(bold("\n  Approved. Applying the undo:"))
        results["undo"] = execute(yt, u_changes, u_skips, apply=True, out_dir=out_dir, label="demo_undo", clock=_clock(2, 16))
    with section("sponsor"):
        _header(6, "Sponsor block: insert above timestamps, never overwrite")
        yt = client_for_day()
        _, videos = yt.scan()
        s_changes, s_skips, already = plan_sponsor(videos, cfg)
        print(f"  already has the block (marker found): {already}")
        print(f"  to insert: {len(s_changes)}   "
              + "  ".join(f"{p}={sum(1 for c in s_changes if c.rule == p)}" for p in ("above-timestamps", "appended-at-end")))
        execute(yt, s_changes[:2], s_skips, apply=False, out_dir=out_dir, label="demo_sponsor_preview", clock=_clock(3))
        results["sponsor"] = execute(yt, s_changes, s_skips, apply=True, out_dir=out_dir, label="demo_sponsor", clock=_clock(3))
        _, videos = yt.scan()
        again, _, _ = plan_sponsor(videos, cfg)
        print(f"\n  Re-run sponsor mode: {green(str(len(again)))} to insert (idempotent)")
        results["sponsor_rerun"] = len(again)

    print(bold("\nDone.") + f" Mock API quota errors: {api.quota_errors} (every stop happened before the API refused)."
          + f"\nChange logs in {out_dir.relative_to(ROOT).as_posix() if out_dir.is_relative_to(ROOT) else out_dir}/")
    return results

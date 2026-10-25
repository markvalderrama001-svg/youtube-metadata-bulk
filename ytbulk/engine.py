"""Scan, plan, apply and undo: the batch workflow.

    scan  -> read every video on the channel (cheap: list calls only)
    plan  -> run the rules, producing a list of proposed changes + guard skips
    apply -> dry run by default; with apply=True, write within today's quota
             budget, log every row, then re-read and verify what was written
    undo  -> build a plan from a change log that puts each video back
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import changelog as cl
from .client import ApiError, Video, YouTubeClient
from .quota import QuotaExceeded
from .rules import Config, opening


# ---------------------------------------------------------------- output ----
def _color_on() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return bool(os.environ.get("FORCE_COLOR")) or sys.stdout.isatty()


def c(text: str, code: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _color_on() else text


def red(t): return c(t, "31")
def green(t): return c(t, "32")
def yellow(t): return c(t, "33")
def cyan(t): return c(t, "36")
def dim(t): return c(t, "90")
def bold(t): return c(t, "1")


def short(s: str, n: int = 78) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


def _display_path(p: Path) -> str:
    try:
        return Path(os.path.relpath(p)).as_posix()
    except ValueError:  # different drive on Windows
        return p.name


# ----------------------------------------------------------------- model ----
@dataclass
class Change:
    video: Video
    action: str
    rule: str
    new_title: str
    new_description: str

    @property
    def title_changed(self) -> bool:
        return self.new_title != self.video.title

    @property
    def desc_changed(self) -> bool:
        return self.new_description != self.video.description


@dataclass
class Skip:
    video: Video
    action: str
    reason: str


@dataclass
class Result:
    counts: dict = field(default_factory=lambda: defaultdict(int))
    log_path: Path | None = None
    updated_ids: list = field(default_factory=list)


# ------------------------------------------------------------------ scan ----
def scan_report(channel: str, videos: list[Video], cfg: Config, scan_cost: int, words: int = 3) -> None:
    print(bold(f"Channel: {channel}") + f"   videos: {len(videos)}   " + dim(f"(scan cost {scan_cost} units)"))
    prefixes = defaultdict(list)
    for v in videos:
        prefixes[" ".join(v.title.split()[:words]).lower()].append(v)
    dupes = {k: vs for k, vs in prefixes.items() if len(vs) > 1}
    print(f"\nRepeated title openings (same first {words} words): {len(dupes)} pattern(s)")
    for k, vs in sorted(dupes.items(), key=lambda kv: -len(kv[1])):
        print(f"  {yellow(str(len(vs)) + 'x')}  \"{k} ...\"")
    title_hits = sum(1 for v in videos if cfg.rewrite_title(v.title))
    desc_hits = sum(1 for v in videos if cfg.rewrite_description(v.description))
    print(f"\nTitles matched by a rule:          {title_hits}")
    print(f"Descriptions with a listed opener: {desc_hits}")
    if cfg.sponsor:
        missing = sum(1 for v in videos if cfg.sponsor.marker not in v.description)
        print(f"Descriptions without sponsor block: {missing}")


# ------------------------------------------------------------------ plan ----
def plan_rules(videos: list[Video], cfg: Config, titles: bool = True, descs: bool = True):
    changes, skips = [], []
    for v in videos:
        t = cfg.rewrite_title(v.title) if titles else None
        d = cfg.rewrite_description(v.description) if descs else None
        if t and t.new is None:
            skips.append(Skip(v, "title", f"{t.rule}: {t.skip_reason}"))
            t = None
        if d and d.new is None:
            skips.append(Skip(v, "description", f"{d.rule}: {d.skip_reason}"))
            d = None
        if not t and not d:
            continue
        action = "+".join(a for a, r in (("title", t), ("description", d)) if r)
        rule = "+".join(r.rule for r in (t, d) if r)
        changes.append(Change(v, action, rule, t.new if t else v.title, d.new if d else v.description))
    return changes, skips


def plan_sponsor(videos: list[Video], cfg: Config):
    changes, skips = [], []
    for v in videos:
        r = cfg.insert_sponsor(v.description)
        if r.new is not None:
            changes.append(Change(v, "sponsor", r.rule, v.title, r.new))
        elif r.rule != "already-present":
            skips.append(Skip(v, "sponsor", f"{r.rule}: {r.skip_reason}"))
    already = len(videos) - len(changes) - len(skips)
    return changes, skips, already


def plan_undo(client: YouTubeClient, rows: list[dict]):
    """Reverse every `updated` row, newest first, only where the video still
    looks exactly as this run left it. Anything edited since is left alone."""
    rows = [r for r in rows if r["status"] == cl.UPDATED]
    current = {v.id: v for v in client.videos(list(dict.fromkeys(r["video_id"] for r in rows)))}
    changes, skips, seen = [], [], set()
    for r in reversed(rows):
        vid = r["video_id"]
        v = current.get(vid)
        if v is None:
            skips.append(Skip(Video(vid, {"title": r["new_title"]}), "undo", "video no longer on the channel"))
            continue
        if vid in seen:
            skips.append(Skip(v, "undo", "video appears twice in the log; undo the later run first"))
            continue
        seen.add(vid)
        if v.title == r["old_title"] and v.description == r["old_description"]:
            skips.append(Skip(v, "undo", "already matches the 'before' values"))
            continue
        drift = [f for f, now, logged in (("title", v.title, r["new_title"]),
                                          ("description", v.description, r["new_description"])) if now != logged]
        if drift:
            skips.append(Skip(v, "undo", f"drifted: {' and '.join(drift)} edited since this run; left as is"))
            continue
        changes.append(Change(v, f"undo:{r['action']}", "restore", r["old_title"], r["old_description"]))
    return changes, skips


# --------------------------------------------------------------- execute ----
def _row(ch: Change, status: str, run_id: str, updated_at: str = "") -> dict:
    return {
        "video_id": ch.video.id, "action": ch.action, "rule": ch.rule, "status": status,
        "old_title": ch.video.title, "new_title": ch.new_title,
        "old_desc_opening": opening(ch.video.description) if ch.desc_changed else "",
        "new_desc_opening": opening(ch.new_description) if ch.desc_changed else "",
        "updated_at": updated_at, "run_id": run_id,
        "old_description": ch.video.description, "new_description": ch.new_description,
    }


def print_diff(ch: Change, budget_ok: bool = True) -> None:
    tag = "" if budget_ok else yellow("  [over today's budget: would defer]")
    print(f"  {cyan(ch.video.id)}  {dim(ch.action + '  rule=' + ch.rule)}{tag}")
    if ch.title_changed:
        print(f"      {red('- ' + ch.video.title)}")
        print(f"      {green('+ ' + ch.new_title)}")
    if ch.desc_changed:
        old_lines, new_lines = ch.video.description.split("\n"), ch.new_description.split("\n")
        removed = [ln for ln in old_lines if ln not in new_lines]
        added = [ln for ln in new_lines if ln not in old_lines]
        for ln in removed[:3]:
            print(f"      {red('- desc: ' + short(ln, 70))}")
        for ln in added[:6]:
            print(f"      {green('+ desc: ' + short(ln, 70))}")
        if not removed and not added:
            print(f"      {dim('~ desc: whitespace only')}")


def execute(client: YouTubeClient, changes: list[Change], skips: list[Skip], *, apply: bool,
            out_dir: Path, label: str, clock=None) -> Result:
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    run_id = f"{label}_{now.strftime('%Y%m%d_%H%M%S')}"
    meter = client.meter
    budget = meter.affordable_updates()
    cost = len(changes) * meter.cost("update")
    print(bold("\nQuota budget"))
    print(f"  used today {meter.used:,} / {meter.daily_limit:,} units"
          + (f" (reserve {meter.reserve:,})" if meter.reserve else "")
          + f"   videos.update = {meter.cost('update')} units")
    print(f"  planned: {len(changes)} update(s) = {cost:,} units   fits today: {budget}"
          + (yellow(f"   -> {len(changes) - budget} will be deferred to the next run") if len(changes) > budget else ""))

    result = Result()
    prefix = "plan" if not apply else "changes"
    log_path = Path(out_dir) / f"yt_{prefix}_{run_id}.csv"
    result.log_path = log_path
    with cl.ChangeLog(log_path) as log:
        if not apply:
            print(bold(f"\nDRY RUN: {len(changes)} proposed change(s), nothing will be written"))
            for i, ch in enumerate(changes):
                print_diff(ch, budget_ok=i < budget)
                log.write(_row(ch, cl.PLANNED, run_id))
                result.counts[cl.PLANNED] += 1
        else:
            print(bold(f"\nAPPLY: writing up to {min(budget, len(changes))} of {len(changes)} change(s)"))
            stop = False
            for i, ch in enumerate(changes):
                status = cl.DEFERRED
                if not stop and i < budget:
                    try:
                        client.update_snippet(ch.video, ch.new_title, ch.new_description)
                        status = cl.UPDATED
                    except QuotaExceeded as e:
                        print(yellow(f"  quota stop: {e}"))
                        stop = True
                    except ApiError as e:
                        status = cl.FAILED
                        print(red(f"  [FAILED]   {ch.video.id}  {e}"))
                stamp = clock().isoformat(timespec="seconds") if status == cl.UPDATED else ""
                log.write(_row(ch, status, run_id, stamp))
                result.counts[status] += 1
                if status == cl.UPDATED:
                    result.updated_ids.append(ch.video.id)
                    print(f"  {green('[UPDATED]')}  {ch.video.id}  {short(ch.new_title, 60)}")
                elif status == cl.DEFERRED:
                    print(f"  {yellow('[DEFERRED]')} {ch.video.id}  {dim('quota budget spent; next run picks it up')}")
        for s in skips:
            log.write({"video_id": s.video.id, "action": s.action, "rule": s.reason, "status": cl.SKIPPED,
                       "old_title": s.video.title, "new_title": s.video.title, "run_id": run_id})
            result.counts[cl.SKIPPED] += 1

    if skips:
        print(bold(f"\nGuards: {len(skips)} skipped before any API call"))
        for s in skips:
            print(f"  {yellow('[SKIPPED]')}  {s.video.id}  {s.action}: {s.reason}")

    if apply and result.updated_ids:
        expected = {ch.video.id: ch for ch in changes}
        fresh = client.videos(result.updated_ids)
        ok = sum(1 for v in fresh if v.title == expected[v.id].new_title
                 and v.description == expected[v.id].new_description)
        mark = green("verified") if ok == len(result.updated_ids) else red("MISMATCH")
        print(f"\nRe-read after write: {mark} {ok}/{len(result.updated_ids)} videos match the log")

    print(bold("\nSummary  ") + "  ".join(f"{k}={v}" for k, v in result.counts.items())
          + f"   quota used today {meter.used:,}/{meter.daily_limit:,}")
    print(f"Change log: {_display_path(log_path)}")
    if not apply and changes:
        print(dim("Review the diff / plan CSV, then re-run with --apply to write."))
    return result

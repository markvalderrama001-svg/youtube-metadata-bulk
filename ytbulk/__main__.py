"""ytbulk command line.

    python -m ytbulk --demo                       offline demo on the synthetic Demo Channel
    python -m ytbulk scan                         read-only report on your channel
    python -m ytbulk run                          dry run of the title/description rules
    python -m ytbulk run --apply [--titles-only | --descs-only]
    python -m ytbulk sponsor [--apply] [--recent 15]
    python -m ytbulk undo output/yt_changes_<run>.csv [--apply]
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

from . import changelog as cl
from .client import YouTubeClient, real_service
from .engine import execute, plan_rules, plan_sponsor, plan_undo, scan_report
from .quota import QuotaMeter
from .rules import load_config, parse_config


def _utf8_stdout():
    if hasattr(sys.stdout, "buffer") and (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env reader (KEY=value lines). Real environment variables win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _meter(cfg, args) -> QuotaMeter:
    q = cfg.quota
    return QuotaMeter(daily_limit=int(q.get("daily_limit", 10_000)), used=args.quota_used,
                      reserve=int(q.get("reserve", 0)),
                      costs={"list": int(q.get("list_cost", 1)), "update": int(q.get("update_cost", 50))})


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    _load_dotenv()
    p = argparse.ArgumentParser(prog="ytbulk", description="Bulk YouTube title/description changes: "
                                "preview, approve, apply, log, reversible.")
    p.add_argument("--demo", action="store_true", help="run the offline demo against a mock API")
    p.add_argument("--section", default="", help="demo only: comma list of scan,plan,apply,rerun,undo,sponsor")
    sub = p.add_subparsers(dest="cmd")

    def common(sp, writes=True):
        sp.add_argument("--config", default=os.environ.get("YTBULK_CONFIG", "config/rules.yaml"))
        sp.add_argument("--channel-id", default=os.environ.get("YT_CHANNEL_ID") or None,
                        help="default: the channel the OAuth token belongs to")
        sp.add_argument("--quota-used", type=int, default=0, help="units already spent today by other tools")
        sp.add_argument("--out-dir", default=os.environ.get("YTBULK_OUTPUT_DIR", "output"))
        if writes:
            g = sp.add_mutually_exclusive_group()
            g.add_argument("--dry-run", action="store_true", help="preview only (the default)")
            g.add_argument("--apply", action="store_true", help="write to YouTube")

    common(sub.add_parser("scan", help="read-only channel report"), writes=False)
    r = sub.add_parser("run", help="apply title / description rules")
    common(r)
    g = r.add_mutually_exclusive_group()
    g.add_argument("--titles-only", action="store_true")
    g.add_argument("--descs-only", action="store_true")
    s = sub.add_parser("sponsor", help="insert the sponsor block above timestamps")
    common(s)
    s.add_argument("--recent", type=int, default=0, help="only the N newest uploads (fast daily catch-up)")
    u = sub.add_parser("undo", help="restore videos from a change log")
    common(u)
    u.add_argument("log", help="a yt_changes_*.csv file written by an --apply run")

    args = p.parse_args(argv)
    if args.demo:
        from .demo import run_demo
        run_demo([x.strip() for x in args.section.split(",") if x.strip()] or None)
        return 0
    if not args.cmd:
        p.print_help()
        return 2

    if not Path(args.config).exists() and args.cmd == "undo":
        args.config = None  # undo needs no rules; default quota settings
    elif not Path(args.config).exists():
        print(f"Config not found: {args.config}. Copy config/rules.example.yaml to config/rules.yaml "
              "and edit the rules, or pass --config.")
        return 2
    cfg = load_config(args.config) if args.config else parse_config({})
    yt = YouTubeClient(real_service(), _meter(cfg, args))
    apply = getattr(args, "apply", False)
    out = Path(args.out_dir)

    if args.cmd == "undo":
        changes, skips = plan_undo(yt, cl.read_log(args.log))
        execute(yt, changes, skips, apply=apply, out_dir=out, label="undo")
        return 0

    channel, videos = yt.scan(args.channel_id)
    if args.cmd == "scan":
        scan_report(channel, videos, cfg, yt.meter.used - args.quota_used)
    elif args.cmd == "run":
        changes, skips = plan_rules(videos, cfg, titles=not args.descs_only, descs=not args.titles_only)
        execute(yt, changes, skips, apply=apply, out_dir=out, label="run")
    elif args.cmd == "sponsor":
        if args.recent:
            videos = videos[: args.recent]
        changes, skips, already = plan_sponsor(videos, cfg)
        print(f"already has the sponsor block: {already}")
        execute(yt, changes, skips, apply=apply, out_dir=out, label="sponsor")
    return 0


if __name__ == "__main__":
    sys.exit(main())

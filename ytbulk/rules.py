"""Rule engine: config loading, title rewrites, description opener fixes,
and the sponsor-block insert.

Every rewrite is a pure function of (current text, config). Nothing here
talks to the API, so the whole engine is unit-testable offline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TITLE_MAX = 100  # YouTube title limit (characters)
DESC_MAX_BYTES = 5000  # YouTube description limit (the API documents it in bytes)

TS_LINE = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s|$)")
TS_HEADER = re.compile(r"^\s*(timestamps?|chapters?)\s*:?\s*$", re.I)


class ConfigError(ValueError):
    pass


@dataclass
class TitleRule:
    name: str
    pattern: re.Pattern
    replace: str


@dataclass
class Opener:
    name: str
    starts_with: str
    replace_with: str = ""


@dataclass
class Sponsor:
    marker: str
    block: str
    max_bytes: int = DESC_MAX_BYTES


@dataclass
class Rewrite:
    """Result of running a rule on one field. `new` is None when skipped."""
    old: str
    new: str | None
    rule: str
    skip_reason: str = ""


@dataclass
class Config:
    title_exact: dict = field(default_factory=dict)
    title_rules: list = field(default_factory=list)
    title_max: int = TITLE_MAX
    openers: list = field(default_factory=list)
    desc_max_bytes: int = DESC_MAX_BYTES
    sponsor: Sponsor | None = None
    quota: dict = field(default_factory=dict)

    # ---------- titles ----------
    def _title_once(self, title: str) -> tuple[str, str] | None:
        if title in self.title_exact:
            return self.title_exact[title], "exact"
        for r in self.title_rules:
            if r.pattern.search(title):
                new = r.pattern.sub(r.replace, title, count=1)
                return re.sub(r"\s{2,}", " ", new).strip(), r.name
        return None

    def rewrite_title(self, title: str) -> Rewrite | None:
        hit = self._title_once(title)
        if hit is None or hit[0] == title:
            return None
        new, rule = hit
        reason = ""
        if not new:
            reason = "rule produced an empty title"
        elif len(new) > self.title_max:
            reason = f"new title is {len(new)} chars (limit {self.title_max})"
        elif "<" in new or ">" in new:
            reason = "YouTube rejects < and > in titles"
        else:
            again = self._title_once(new)
            if again is not None and again[0] != new:
                reason = f"rule '{rule}' is not idempotent (its output would be rewritten again)"
        return Rewrite(title, None if reason else new, rule, reason)

    # ---------- descriptions ----------
    def _desc_once(self, desc: str) -> tuple[str, str] | None:
        if not desc:
            return None
        lines = desc.split("\n")
        first = lines[0].strip()
        for o in self.openers:
            if first.lower().startswith(o.starts_with.lower()):
                rest_of_line = first[len(o.starts_with):].strip()
                head = " ".join(p for p in (o.replace_with.strip(), rest_of_line) if p)
                body = lines[1:]
                if not head:  # opener was the whole line: drop it and the blank lines after it
                    while body and not body[0].strip():
                        body.pop(0)
                    return "\n".join(body), o.name
                return "\n".join([head] + body), o.name
        return None

    def rewrite_description(self, desc: str) -> Rewrite | None:
        hit = self._desc_once(desc)
        if hit is None or hit[0] == desc:
            return None
        new, rule = hit
        reason = ""
        if not new.strip():
            reason = "description would be empty"
        elif byte_len(new) > self.desc_max_bytes:
            reason = f"description would be {byte_len(new):,} bytes (limit {self.desc_max_bytes:,})"
        else:
            again = self._desc_once(new)
            if again is not None and again[0] != new:
                reason = f"opener '{rule}' is not idempotent"
        return Rewrite(desc, None if reason else new, rule, reason)

    # ---------- sponsor block ----------
    def insert_sponsor(self, desc: str) -> Rewrite:
        """Insert the sponsor block above the timestamps (or append at the end).

        Never edits or removes existing text: the result is always the original
        lines with the block (plus one blank line) spliced in. Returns a Rewrite
        whose `rule` is the placement and whose `new` is None when skipped.
        """
        if self.sponsor is None:
            raise ConfigError("no `sponsor:` section in the config")
        sp = self.sponsor
        if sp.marker in desc:
            return Rewrite(desc, None, "already-present", "marker already in description")
        lines = desc.split("\n") if desc else []
        idx = find_timestamps(lines)
        block = sp.block.strip("\n")
        if idx is not None:
            new_lines = lines[:idx] + [block, ""] + lines[idx:]
            placement = "above-timestamps"
        else:
            new_lines = lines + (["", block] if lines else [block])
            placement = "appended-at-end"
        new = "\n".join(new_lines)
        if byte_len(new) > sp.max_bytes:
            return Rewrite(desc, None, placement,
                           f"would be {byte_len(new):,} bytes (limit {sp.max_bytes:,})")
        return Rewrite(desc, new, placement)


def byte_len(s: str) -> int:
    return len(s.encode("utf-8"))


def find_timestamps(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        if TS_HEADER.match(line):
            return i
    for i, line in enumerate(lines):
        if TS_LINE.match(line):
            return i
    return None


def opening(desc: str) -> str:
    """First line of a description, as recorded in the change log."""
    return desc.split("\n", 1)[0].strip() if desc else ""


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return parse_config(raw)


def parse_config(raw: dict) -> Config:
    t = raw.get("titles") or {}
    d = raw.get("descriptions") or {}
    rules = []
    for i, r in enumerate(t.get("rules") or []):
        if "find" not in r or "replace" not in r:
            raise ConfigError(f"titles.rules[{i}] needs `find` and `replace`")
        flags = re.I if r.get("ignore_case") else 0
        try:
            pat = re.compile(r["find"], flags)
        except re.error as e:
            raise ConfigError(f"titles.rules[{i}] bad regex: {e}") from e
        rules.append(TitleRule(r.get("name", f"rule{i + 1}"), pat, r["replace"]))
    openers = []
    for i, o in enumerate(d.get("openers") or []):
        if not o.get("starts_with"):
            raise ConfigError(f"descriptions.openers[{i}] needs `starts_with`")
        openers.append(Opener(o.get("name", f"opener{i + 1}"), o["starts_with"], o.get("replace_with") or ""))
    sponsor = None
    if raw.get("sponsor"):
        s = raw["sponsor"]
        if not s.get("marker") or not s.get("block"):
            raise ConfigError("sponsor needs `marker` and `block`")
        if s["marker"] not in s["block"]:
            raise ConfigError("sponsor.marker must appear in sponsor.block, or re-runs would insert it twice")
        sponsor = Sponsor(s["marker"], s["block"], int(s.get("max_description_bytes", DESC_MAX_BYTES)))
    return Config(
        title_exact=dict(t.get("exact") or {}),
        title_rules=rules,
        title_max=int(t.get("max_length", TITLE_MAX)),
        openers=openers,
        desc_max_bytes=int(d.get("max_bytes", DESC_MAX_BYTES)),
        sponsor=sponsor,
        quota=dict(raw.get("quota") or {}),
    )

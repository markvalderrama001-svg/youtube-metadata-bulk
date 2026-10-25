"""Synthetic "Demo Channel": 15 made-up videos for the demo and tests.

Every ID, title and description here is invented. The channel is a fictional
small-business finance tutorial channel with the same problems the real tool
was built for: a repetitive "We Rated Every ..." title formula and a
boilerplate first line pasted into every description.
"""
from __future__ import annotations

CHANNEL_TITLE = "Demo Channel"
CHANNEL_ID = "UCdemoChannel000000000"  # synthetic

OPENER = "It's time for another video!"

TIMESTAMPS = "Timestamps:\n0:00 Intro\n1:12 The setup\n4:30 Walkthrough\n9:45 Wrap-up"
CHAPTERS = "Chapters\n00:00 Intro\n02:10 Example entries\n07:55 Common mistakes"
FOOTER = "Questions? Leave a comment and we will answer it in a future video."

_FILLER = ("Every month-end close is a chance to tighten the process. In this series we walk through "
           "the habits, checklists and small automations that keep the books clean without overtime. ")


def _desc(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)


def _long_desc() -> str:
    body = _FILLER * 27  # ~4,940 bytes: the sponsor block will not fit under 5,000
    return _desc("A deep dive into spreadsheet shortcuts for accountants.", body.strip(), FOOTER)


VIDEOS = [
    {"id": "demoVid0001", "snippet": {  # synthetic
        "title": "We Rated Every Budgeting Apps (Full Review)", "categoryId": "27", "tags": ["budgeting", "apps"],
        "description": _desc(OPENER, "We rank twelve budgeting apps from must-have to skip.", TIMESTAMPS, FOOTER)}},
    {"id": "demoVid0002", "snippet": {  # synthetic
        "title": "We Rated Every Accounting Software (Full Review)", "categoryId": "27", "tags": ["accounting"],
        "description": _desc(f"{OPENER} Today: accounting software for a five-person team.", FOOTER)}},
    {"id": "demoVid0003", "snippet": {  # synthetic
        "title": "We Rated Every Business Credit Cards", "categoryId": "27",
        "description": _desc(OPENER, "Rewards, controls and receipt capture compared.", CHAPTERS, FOOTER)}},
    {"id": "demoVid0004", "snippet": {  # synthetic
        "title": "We Rated Every Receipt Scanners", "categoryId": "27",
        "description": _desc("Six receipt scanners, one shoebox of receipts.", TIMESTAMPS)}},
    {"id": "demoVid0005", "snippet": {  # synthetic
        "title": "Here Are The 10 BEST Expense Trackers...", "categoryId": "27",
        "description": _desc(OPENER, "Ten expense trackers tested on the same month of spend.", FOOTER)}},
    {"id": "demoVid0006", "snippet": {  # synthetic
        "title": "Here Are The 7 BEST Invoicing Tools...", "categoryId": "27",
        "description": _desc("Seven invoicing tools and how fast they get you paid.", TIMESTAMPS, FOOTER)}},
    {"id": "demoVid0007", "snippet": {  # synthetic
        "title": "Everything You NEED To Know About Accruals", "categoryId": "27",
        "description": _desc("Accruals, deferrals and the reversing entry.", CHAPTERS)}},
    {"id": "demoVid0008", "snippet": {  # synthetic
        "title": "How To Close The Books In 5 Days", "categoryId": "27",
        "description": _desc("A five-day close calendar you can copy.", TIMESTAMPS, FOOTER)}},
    {"id": "demoVid0009", "snippet": {  # synthetic
        "title": "Bank Reconciliation Walkthrough (Step by Step)", "categoryId": "27",
        "description": _desc(OPENER, "A full bank rec for E100 Demo Co, start to finish.", FOOTER)}},
    {"id": "demoVid0010", "snippet": {  # synthetic
        "title": "We Rated Every Payroll Providers For Small Teams And Agencies With Remote Contractors (Full Review)",
        "categoryId": "27", "description": _desc("Payroll providers compared for distributed teams.", FOOTER)}},
    {"id": "demoVid0011", "snippet": {  # synthetic
        "title": "Month-End Close Checklist", "categoryId": "27",
        "description": _desc("The checklist we use every month.",
                             "-----------------------\nSponsor: Globex Cloud\nTry it free: https://example.com/?ref=DEMO",
                             TIMESTAMPS)}},
    {"id": "demoVid0012", "snippet": {  # synthetic
        "title": "We Rated Every Spreadsheet Shortcuts (Full Review)", "categoryId": "27",
        "description": _long_desc()}},
    {"id": "demoVid0013", "snippet": {  # synthetic
        "title": "Cash vs Accrual Accounting", "categoryId": "27",
        "description": _desc("Which basis fits a growing business, and when to switch.", FOOTER)}},
    {"id": "demoVid0014", "snippet": {  # synthetic
        "title": "We Rated Every Bookkeeping Habits", "categoryId": "27",
        "description": _desc(OPENER, "Small habits that save hours at month end.", TIMESTAMPS)}},
    {"id": "demoVid0015", "snippet": {  # synthetic
        "title": "Here Are The 5 BEST Tax Prep Tips...", "categoryId": "27",
        "description": _desc("Five things to do before you hand files to your preparer.", FOOTER)}},
]

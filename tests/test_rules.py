import pytest

from ytbulk.rules import ConfigError, parse_config


def test_regex_rule_rewrites_title(cfg):
    r = cfg.rewrite_title("We Rated Every Budgeting Apps (Full Review)")
    assert r.new == "Budgeting Apps: Which Ones Are Actually Worth It?"
    assert r.rule == "full-review"


def test_first_matching_rule_wins_and_exact_beats_regex(cfg):
    assert cfg.rewrite_title("We Rated Every Receipt Scanners").rule == "rated"
    r = cfg.rewrite_title("Everything You NEED To Know About Accruals")
    assert r.rule == "exact" and r.new.startswith("Accruals Explained")


def test_no_match_returns_none(cfg):
    assert cfg.rewrite_title("Cash vs Accrual Accounting") is None


def test_rewrite_is_a_fixed_point(cfg):
    new = cfg.rewrite_title("Here Are The 10 BEST Expense Trackers...").new
    assert new == "10 Expense Trackers Worth Using (And What to Skip)"
    assert cfg.rewrite_title(new) is None


def test_title_over_100_chars_is_skipped_not_truncated(cfg):
    long = "We Rated Every Payroll Providers For Small Teams And Agencies With Remote Contractors (Full Review)"
    assert len(long) <= 100
    r = cfg.rewrite_title(long)
    assert r.new is None and "limit 100" in r.skip_reason


def test_angle_brackets_refused():
    cfg = parse_config({"titles": {"rules": [{"find": "^Old (.+)$", "replace": r"<New> \1"}]}})
    r = cfg.rewrite_title("Old thing")
    assert r.new is None and "<" in r.skip_reason


def test_non_idempotent_rule_refused():
    cfg = parse_config({"titles": {"rules": [{"name": "grow", "find": "^(.+)$", "replace": r"\1!"}]}})
    r = cfg.rewrite_title("Hello")
    assert r.new is None and "not idempotent" in r.skip_reason


def test_opener_on_own_line_is_dropped_with_blank_lines(cfg):
    desc = "It's time for another video!\n\nWe rank apps.\n\n0:00 Intro"
    assert cfg.rewrite_description(desc).new == "We rank apps.\n\n0:00 Intro"


def test_opener_case_insensitive_and_rest_of_line_kept(cfg):
    desc = "IT'S TIME FOR ANOTHER VIDEO! Today: payroll.\nMore text"
    assert cfg.rewrite_description(desc).new == "Today: payroll.\nMore text"


def test_opener_replace_with():
    cfg = parse_config({"descriptions": {"openers": [{"starts_with": "Hey guys!", "replace_with": "Welcome back."}]}})
    assert cfg.rewrite_description("Hey guys! Today we talk tax.").new == "Welcome back. Today we talk tax."


def test_description_without_opener_untouched(cfg):
    assert cfg.rewrite_description("A clean description.") is None
    assert cfg.rewrite_description("") is None


@pytest.mark.parametrize("raw, msg", [
    ({"titles": {"rules": [{"find": "("}]}}, "needs `find` and `replace`"),
    ({"titles": {"rules": [{"find": "(", "replace": "x"}]}}, "bad regex"),
    ({"sponsor": {"marker": "abc", "block": "no marker here"}}, "must appear in sponsor.block"),
])
def test_config_validation(raw, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config(raw)

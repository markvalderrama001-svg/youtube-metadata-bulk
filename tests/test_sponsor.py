from ytbulk.rules import byte_len, parse_config

BLOCK = "-----\nSponsor: Globex Cloud\nhttps://example.com/?ref=DEMO"


def make(max_bytes=5000):
    return parse_config({"sponsor": {"marker": "example.com/?ref=DEMO", "block": BLOCK,
                                     "max_description_bytes": max_bytes}})


def test_inserted_above_timestamp_header():
    desc = "Intro text.\n\nTimestamps:\n0:00 Intro\n1:30 Main"
    r = make().insert_sponsor(desc)
    assert r.rule == "above-timestamps"
    assert r.new == "Intro text.\n\n" + BLOCK + "\n\nTimestamps:\n0:00 Intro\n1:30 Main"


def test_inserted_above_first_timestamp_line_without_header():
    r = make().insert_sponsor("Intro.\n00:00 Start\n01:00:15 Long part")
    assert r.new.index("Sponsor") < r.new.index("00:00 Start")


def test_appended_when_no_timestamps():
    r = make().insert_sponsor("Just text.")
    assert r.rule == "appended-at-end" and r.new == "Just text.\n\n" + BLOCK


def test_never_overwrites_existing_text():
    desc = "Line one\nLine two\n\nChapters\n0:00 a\n2:00 b\nFooter"
    new = make().insert_sponsor(desc).new
    assert new.replace(BLOCK + "\n\n", "", 1) == desc


def test_idempotent_marker_check():
    cfg = make()
    once = cfg.insert_sponsor("Text\n0:00 Intro").new
    again = cfg.insert_sponsor(once)
    assert again.new is None and again.rule == "already-present"
    assert once.count("Sponsor:") == 1


def test_5000_byte_guard():
    cfg = make()
    near_limit = "x" * (5000 - len(BLOCK) - 1)
    r = cfg.insert_sponsor(near_limit)
    assert r.new is None and "limit 5,000" in r.skip_reason


def test_guard_counts_bytes_not_characters():
    cfg = make()
    desc = "é" * 2480  # 2,480 characters but 4,960 UTF-8 bytes
    assert len(desc) + len(BLOCK) + 2 < 5000
    assert byte_len(desc) == 4960
    assert cfg.insert_sponsor(desc).new is None


def test_exactly_at_limit_is_allowed():
    cfg = make()
    desc = "x" * (5000 - len(BLOCK) - 2)
    r = cfg.insert_sponsor(desc)
    assert r.new is not None and byte_len(r.new) == 5000

import pytest

from ytbulk.engine import execute, plan_rules
from ytbulk.quota import QuotaExceeded, QuotaMeter


def test_200_updates_a_day_minus_verification():
    m = QuotaMeter()
    assert m.remaining // 50 == 200
    assert m.affordable_updates() == 199  # 199 x 50 + 4 list calls to verify = 9,954
    assert m.affordable_updates(verify=False) == 200


def test_charge_raises_before_exceeding():
    m = QuotaMeter(daily_limit=120, used=60)
    m.charge("update")
    assert m.used == 110
    with pytest.raises(QuotaExceeded):
        m.charge("update")
    assert m.used == 110  # the refused call was not counted


def test_reserve_is_never_spent():
    m = QuotaMeter(daily_limit=10_000, reserve=2_000)
    assert m.affordable_updates() == 159


def test_apply_stops_at_budget_and_defers_rest(cfg, api, make_client, tmp_path):
    yt = make_client(used=9_700)
    _, videos = yt.scan()
    changes, skips = plan_rules(videos, cfg)
    assert len(changes) == 11
    res = execute(yt, changes, skips, apply=True, out_dir=tmp_path, label="t")
    assert res.counts["updated"] == 5
    assert res.counts["deferred_quota"] == 6
    assert len(api.updates) == 5
    assert api.quota_errors == 0  # the tool stopped first; the API never refused
    assert yt.meter.used <= 10_000


def test_dry_run_makes_no_writes(cfg, api, make_client, tmp_path):
    yt = make_client()
    _, videos = yt.scan()
    changes, skips = plan_rules(videos, cfg)
    res = execute(yt, changes, skips, apply=False, out_dir=tmp_path, label="t")
    assert res.counts["planned"] == 11
    assert api.updates == [] and "update" not in api.calls


def test_titles_only_and_descs_only(cfg, make_client):
    yt = make_client()
    _, videos = yt.scan()
    t, _ = plan_rules(videos, cfg, descs=False)
    d, _ = plan_rules(videos, cfg, titles=False)
    assert all(not c.desc_changed for c in t) and len(t) == 10
    assert all(not c.title_changed for c in d) and len(d) == 6

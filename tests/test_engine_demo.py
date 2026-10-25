from ytbulk.demo import run_demo
from ytbulk.engine import execute, plan_rules, plan_sponsor


def test_scan_paginates(make_client):
    yt = make_client()
    channel, videos = yt.scan()
    assert channel == "Demo Channel" and len(videos) == 15
    assert yt.meter.used == 4  # channels.list + 2 playlist pages + 1 videos.list


def test_update_round_trips_writable_fields(cfg, api, make_client, tmp_path):
    yt = make_client()
    _, videos = yt.scan()
    changes, skips = plan_rules(videos, cfg)
    execute(yt, changes, skips, apply=True, out_dir=tmp_path, label="t")
    sn = api.store["demoVid0001"]
    assert sn["tags"] == ["budgeting", "apps"] and sn["categoryId"] == "27"


def test_api_failure_is_logged_and_run_continues(cfg, api, make_client, tmp_path):
    yt = make_client()
    _, videos = yt.scan()
    changes, skips = plan_rules(videos, cfg)
    del api.store["demoVid0002"]  # deleted between scan and write
    res = execute(yt, changes, skips, apply=True, out_dir=tmp_path, label="t")
    assert res.counts["failed"] == 1 and res.counts["updated"] == 10


def test_sponsor_mode_end_to_end(cfg, api, make_client, tmp_path):
    yt = make_client()
    _, videos = yt.scan()
    ch, sk, already = plan_sponsor(videos, cfg)
    assert already == 1 and [s.video.id for s in sk] == ["demoVid0012"]
    execute(yt, ch, sk, apply=True, out_dir=tmp_path, label="s")
    _, videos = yt.scan()
    again, _, _ = plan_sponsor(videos, cfg)
    assert again == []
    assert all(len(sn["description"].encode()) <= 5000 for sn in api.store.values())


def test_full_demo_runs(tmp_path, capsys):
    res = run_demo(out_dir=tmp_path)
    out = capsys.readouterr().out
    assert res["day1"].counts["updated"] == 5 and res["day1"].counts["deferred_quota"] == 6
    assert res["day2"].counts["updated"] == 6
    assert res["rerun_changes"] == 0
    assert res["undo"].counts["updated"] == 5 and res["undo"].counts["skipped"] == 1
    assert res["sponsor_rerun"] == 0
    assert res["api"].quota_errors == 0
    assert "DRY RUN" in out and "verified" in out

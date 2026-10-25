import csv

import pytest

from ytbulk import changelog as cl
from ytbulk import demo_data
from ytbulk.engine import execute, plan_rules, plan_sponsor, plan_undo


def _apply(yt, cfg, tmp_path, label="run"):
    _, videos = yt.scan()
    changes, skips = plan_rules(videos, cfg)
    return execute(yt, changes, skips, apply=True, out_dir=tmp_path, label=label)


def test_change_log_columns_and_rows(cfg, make_client, tmp_path):
    res = _apply(make_client(), cfg, tmp_path)
    rows = list(csv.DictReader(res.log_path.open(encoding="utf-8")))
    assert list(rows[0].keys()) == cl.FIELDS
    upd = [r for r in rows if r["status"] == "updated"]
    assert len(upd) == 11 and all(r["updated_at"] for r in upd)
    r1 = next(r for r in upd if r["video_id"] == "demoVid0001")
    assert r1["old_title"] == "We Rated Every Budgeting Apps (Full Review)"
    assert r1["old_desc_opening"] == "It's time for another video!"
    assert r1["new_desc_opening"].startswith("We rank twelve")
    title_only = next(r for r in upd if r["video_id"] == "demoVid0004")
    assert title_only["old_desc_opening"] == "" and title_only["old_description"] == title_only["new_description"]
    skipped = [r for r in rows if r["status"] == "skipped"]
    assert [r["video_id"] for r in skipped] == ["demoVid0010"]


def test_log_name_is_timestamped(cfg, make_client, tmp_path):
    res = _apply(make_client(), cfg, tmp_path)
    assert res.log_path.name.startswith("yt_changes_run_") and res.log_path.suffix == ".csv"


def test_undo_restores_everything(cfg, api, make_client, tmp_path):
    yt = make_client()
    res = _apply(yt, cfg, tmp_path)
    changes, skips = plan_undo(yt, cl.read_log(res.log_path))
    assert len(changes) == 11 and not skips
    execute(yt, changes, skips, apply=True, out_dir=tmp_path, label="undo")
    original = {v["id"]: v["snippet"] for v in demo_data.VIDEOS}
    for vid, sn in api.store.items():
        assert sn["title"] == original[vid]["title"]
        assert sn["description"] == original[vid]["description"]
        assert sn.get("tags") == original[vid].get("tags")  # writable fields round-tripped


def test_undo_dry_run_writes_nothing(cfg, api, make_client, tmp_path):
    yt = make_client()
    res = _apply(yt, cfg, tmp_path)
    n = len(api.updates)
    changes, skips = plan_undo(yt, cl.read_log(res.log_path))
    execute(yt, changes, skips, apply=False, out_dir=tmp_path, label="undo")
    assert len(api.updates) == n


def test_undo_skips_videos_edited_since(cfg, api, make_client, tmp_path):
    yt = make_client()
    res = _apply(yt, cfg, tmp_path)
    api.edit_in_studio("demoVid0003", title="Hand-edited title")
    changes, skips = plan_undo(yt, cl.read_log(res.log_path))
    assert "demoVid0003" not in {c.video.id for c in changes}
    assert any(s.video.id == "demoVid0003" and "drifted" in s.reason for s in skips)
    execute(yt, changes, skips, apply=True, out_dir=tmp_path, label="undo")
    assert api.store["demoVid0003"]["title"] == "Hand-edited title"


def test_undo_ignores_deferred_rows(cfg, make_client, tmp_path):
    yt = make_client(used=9_700)
    res = _apply(yt, cfg, tmp_path)
    rows = cl.read_log(res.log_path)
    yt = make_client()
    changes, _ = plan_undo(yt, rows)
    assert len(changes) == 5


def test_undo_twice_is_a_no_op(cfg, make_client, tmp_path):
    yt = make_client()
    res = _apply(yt, cfg, tmp_path)
    rows = cl.read_log(res.log_path)
    c, s = plan_undo(yt, rows)
    execute(yt, c, s, apply=True, out_dir=tmp_path, label="undo")
    c2, s2 = plan_undo(yt, rows)
    assert c2 == [] and all("already matches" in x.reason for x in s2)


def test_undo_of_sponsor_run(cfg, api, make_client, tmp_path):
    yt = make_client()
    _, videos = yt.scan()
    ch, sk, _ = plan_sponsor(videos, cfg)
    res = execute(yt, ch, sk, apply=True, out_dir=tmp_path, label="sponsor")
    c, s = plan_undo(yt, cl.read_log(res.log_path))
    execute(yt, c, s, apply=True, out_dir=tmp_path, label="undo")
    assert sum(cfg.sponsor.marker in sn["description"] for sn in api.store.values()) == 1


def test_read_log_rejects_foreign_csv(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a ytbulk change log"):
        cl.read_log(p)

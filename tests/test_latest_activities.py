import json
from pathlib import Path

from split_garmin_json import refresh_latest_activities


def write_activity_file(path, date, activity_id):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": date, "activities": [{"activity_id": activity_id}]}), encoding="utf-8")


def test_current_export_activity_replaces_older_latest(tmp_path):
    old = tmp_path / "2026" / "08" / "2026-08-23_activities.json"
    current = tmp_path / "2026" / "08" / "2026-08-26_activities.json"
    write_activity_file(old, "2026-08-23", 23)
    write_activity_file(current, "2026-08-26", 26)

    refresh_latest_activities(tmp_path, None, current, True)

    latest = json.loads((tmp_path / "latest_activities.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-08-26"
    assert latest["activities"][0]["activity_id"] == 26


def test_no_activity_keeps_newest_existing_activity(tmp_path):
    old = tmp_path / "2026" / "08" / "2026-08-23_activities.json"
    newer = tmp_path / "2026" / "08" / "2026-08-25_activities.json"
    write_activity_file(old, "2026-08-23", 23)
    write_activity_file(newer, "2026-08-25", 25)

    refresh_latest_activities(tmp_path, None, tmp_path / "2026" / "08" / "2026-08-26_activities.json", False)

    latest = json.loads((tmp_path / "latest_activities.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-08-25"
    assert latest["activities"][0]["activity_id"] == 25


def test_historical_export_does_not_replace_newer_latest(tmp_path):
    newer = tmp_path / "2026" / "08" / "2026-08-26_activities.json"
    historical = tmp_path / "2026" / "08" / "2026-08-20_activities.json"
    write_activity_file(newer, "2026-08-26", 26)
    write_activity_file(historical, "2026-08-20", 20)
    (tmp_path / "latest_activities.json").write_text(newer.read_text(encoding="utf-8"), encoding="utf-8")

    refresh_latest_activities(tmp_path, None, historical, True)

    latest = json.loads((tmp_path / "latest_activities.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-08-26"
    assert latest["activities"][0]["activity_id"] == 26

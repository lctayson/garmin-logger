import json
from datetime import date, timedelta

from split_garmin_json import refresh_latest_activities


def write_activity_file(path, date_text, activity_id):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": date_text, "activities": [{"activity_id": activity_id}]}), encoding="utf-8")


def read_latest(path):
    return json.loads((path / "latest_activities.json").read_text(encoding="utf-8"))


def test_today_with_activity_replaces_older_latest(tmp_path):
    today = date(2026, 8, 26)
    old = tmp_path / "2026" / "08" / "2026-08-23_activities.json"
    current = tmp_path / "2026" / "08" / "2026-08-26_activities.json"
    write_activity_file(old, "2026-08-23", 23)
    write_activity_file(current, "2026-08-26", 26)
    (tmp_path / "latest_activities.json").write_text(old.read_text(encoding="utf-8"), encoding="utf-8")

    assert refresh_latest_activities(tmp_path, today, current, True, today) is True
    latest = read_latest(tmp_path)
    assert latest["date"] == "2026-08-26"
    assert latest["activities"][0]["activity_id"] == 26


def test_today_without_activity_keeps_previous_latest(tmp_path):
    today = date(2026, 8, 26)
    old = tmp_path / "2026" / "08" / "2026-08-23_activities.json"
    write_activity_file(old, "2026-08-23", 23)
    (tmp_path / "latest_activities.json").write_text(old.read_text(encoding="utf-8"), encoding="utf-8")

    assert refresh_latest_activities(tmp_path, today, tmp_path / "2026" / "08" / "2026-08-26_activities.json", False, today) is False
    latest = read_latest(tmp_path)
    assert latest["date"] == "2026-08-23"
    assert latest["activities"][0]["activity_id"] == 23


def test_historical_export_never_replaces_latest(tmp_path):
    today = date(2026, 8, 26)
    newer = tmp_path / "2026" / "08" / "2026-08-26_activities.json"
    historical = tmp_path / "2026" / "08" / "2026-08-13_activities.json"
    write_activity_file(newer, "2026-08-26", 26)
    write_activity_file(historical, "2026-08-13", 13)
    (tmp_path / "latest_activities.json").write_text(newer.read_text(encoding="utf-8"), encoding="utf-8")

    assert refresh_latest_activities(tmp_path, date(2026, 8, 13), historical, True, today) is False
    latest = read_latest(tmp_path)
    assert latest["date"] == "2026-08-26"
    assert latest["activities"][0]["activity_id"] == 26


def test_historical_export_with_activity_does_not_require_recent_activity_lookup(tmp_path):
    today = date(2026, 8, 26)
    historical = tmp_path / "2026" / "08" / "2026-08-13_activities.json"
    write_activity_file(historical, "2026-08-13", 13)
    (tmp_path / "latest_activities.json").write_text(
        json.dumps({"date": "2026-08-23", "activities": [{"activity_id": 23}]}),
        encoding="utf-8",
    )

    assert refresh_latest_activities(tmp_path, date(2026, 8, 13), historical, True, today) is False
    latest = read_latest(tmp_path)
    assert latest["date"] == "2026-08-23"
    assert latest["activities"][0]["activity_id"] == 23

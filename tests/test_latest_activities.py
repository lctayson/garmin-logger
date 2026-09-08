import json
from datetime import date
from pathlib import Path

from split_garmin_json import normalize_activity, refresh_latest_activities


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


def test_normalize_activity_preserves_target_split_format_without_elapsed_time():
    expected_columns = [
        "step_type", "lap", "time", "avg_pace", "avg_gap", "avg_hr", "max_hr",
        "start_hr", "min_hr", "end_hr", "avg_run_cadence", "calories", "best_pace",
        "max_run_cadence", "moving_time", "avg_moving_pace", "distance", "elevation_gain",
        "elevation_loss", "stride_length", "avg_vertical_oscillation", "avg_ground_contact_time",
        "normalized_power", "avg_power", "max_power", "avg_vertical_ratio",
    ]
    activity = {
        "name": "Malolos - 5 × 3min VO₂ Intervals",
        "activity_id": 24277674810,
        "time": "42:23",
        "elapsed_time": "50:07",
        "duration_min": 42.38,
        "aerobic_te": 3.6,
        "anaerobic_te": 0.5,
        "training_effect_label": "VO2MAX",
        "splits": {
            "columns": expected_columns.copy(),
            "data": [
                ["WARMUP", 1, "10:01", "7:23", "7:27", 137.0, 148.0],
            ],
        },
    }

    normalized = normalize_activity(activity)

    assert normalized["splits"]["columns"] == expected_columns
    assert "elapsed_time" not in normalized["splits"]["columns"]
    assert "duration_min" not in normalized
    assert "aerobic_te" not in normalized
    assert "anaerobic_te" not in normalized
    assert "training_effect_label" not in normalized

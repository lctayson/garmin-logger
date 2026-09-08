import json
from datetime import date
from pathlib import Path

from split_garmin_json import normalize_activity, refresh_latest_activities


def read_latest(path):
    return json.loads((path / "latest_activities.json").read_text(encoding="utf-8"))


def write_activity_file(path, date_text, activity_id):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": date_text, "activities": [{"activity_id": activity_id}]}), encoding="utf-8")


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


def test_normalize_activity_matches_target_schema_order():
    activity = {
        "weather": {"temperature": 24.4},
        "exercise_load": 138.2,
        "name": "Malolos - 5 × 3min VO₂ Intervals",
        "activityId": 24277674810,
        "type": "running",
        "distance": 6.13,
        "time": "42:23",
        "elapsed_time": "50:07",
        "moving_time": "42:20",
        "avg_pace": "6:55",
        "gap": "6:57",
        "avg_hr": 152.0,
        "max_hr": 176.0,
        "recovery_hr": 24,
        "elevation_gain": 6.0,
        "elevation_loss": 9.0,
        "start_time_local": "2026-09-08T06:31:13.0",
        "training_effect": {"label": "VO2MAX", "aerobic": 3.6},
        "interval_drift": {"work_reps": 5},
        "activity_splits": [
            {
                "avg_vertical_ratio": 9.6,
                "time_seconds": 600.542,
                "step_type": "WARMUP",
                "lap": 1,
                "time": "10:01",
                "avg_pace": "7:23",
                "avg_gap": "7:27",
                "avg_hr": 137.0,
                "max_hr": 148.0,
                "start_hr": 104,
                "min_hr": 104,
                "end_hr": 148,
                "avg_run_cadence": 175.0,
                "calories": 93.0,
                "best_pace": "6:24",
                "max_run_cadence": 188.0,
                "moving_time": "10:00",
                "avg_moving_pace": "7:22",
                "distance": 1.36,
                "elevation_gain": 0.0,
                "elevation_loss": 2.0,
                "stride_length": 0.77,
                "avg_vertical_oscillation": 7.4,
                "avg_ground_contact_time": 268.1,
                "normalized_power": 234.0,
                "avg_power": 233.0,
                "max_power": 272.0,
            }
        ],
        "hr_zones": {"columns": ["zone", "range", "time", "percent"], "data": []},
        "power_zones": {"columns": ["zone", "range", "time", "percent"], "data": []},
        "lap_count": 12,
        "duration_min": 42.38,
        "aerobic_te": 3.6,
        "anaerobic_te": 0.5,
        "training_effect_label": "VO2MAX",
    }

    normalized = normalize_activity(activity)

    expected_activity_keys = [
        "name", "activity_id", "type", "distance", "time", "elapsed_time", "moving_time",
        "avg_pace", "gap", "avg_hr", "max_hr", "recovery_hr", "elevation_gain", "elevation_loss",
        "load", "start_time_local", "training_effect", "interval_drift", "splits", "weather",
        "hr_zones", "power_zones", "lap_count",
    ]
    assert list(normalized.keys()) == expected_activity_keys
    assert normalized["activity_id"] == 24277674810
    assert normalized["load"] == 138.2
    assert "exercise_load" not in normalized
    assert "activity_splits" not in normalized
    assert "duration_min" not in normalized
    assert "aerobic_te" not in normalized
    assert "anaerobic_te" not in normalized
    assert "training_effect_label" not in normalized

    expected_split_columns = [
        "step_type", "lap", "time", "avg_pace", "avg_gap", "avg_hr", "max_hr", "start_hr",
        "min_hr", "end_hr", "avg_run_cadence", "calories", "best_pace", "max_run_cadence",
        "moving_time", "avg_moving_pace", "distance", "elevation_gain", "elevation_loss",
        "stride_length", "avg_vertical_oscillation", "avg_ground_contact_time", "normalized_power",
        "avg_power", "max_power", "avg_vertical_ratio",
    ]
    assert normalized["splits"]["columns"] == expected_split_columns
    assert normalized["splits"]["data"][0] == [
        "WARMUP", 1, "10:01", "7:23", "7:27", 137.0, 148.0, 104, 104, 148,
        175.0, 93.0, "6:24", 188.0, "10:00", "7:22", 1.36, 0.0, 2.0, 0.77,
        7.4, 268.1, 234.0, 233.0, 272.0, 9.6,
    ]

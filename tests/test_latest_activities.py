import json
from datetime import date

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


def test_latest_activity_schema_removes_legacy_fields_and_preserves_analysis_fields():
    activity = {
        "name": "Malolos - 5 × 3min VO₂ Intervals",
        "activity_id": 24277674810,
        "type": "running",
        "distance": 6.13,
        "duration_min": 42.38,
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
        "aerobic_te": 3.6,
        "anaerobic_te": 0.5,
        "training_effect_label": "VO2MAX",
        "load": 138.2,
        "start_time_local": "2026-09-08T06:31:13.0",
        "training_effect": {
            "label": "VO2MAX",
            "aerobic": 3.6,
            "aerobic_message": "IMPROVING_VO2_MAX",
            "anaerobic": 0.5,
            "anaerobic_message": "NO_ANAEROBIC_BENEFIT",
        },
        "interval_drift": {
            "work_reps": 5,
            "pace_ef_drift_pct": -19.7,
            "hr_delta_bpm": 22.0,
            "power_ef_drift_pct": -28.4,
            "power_delta_w": 107.0,
        },
        "splits": {"columns": ["step_type"], "data": [["WARMUP"]]},
        "weather": {"temperature": 24.4},
        "hr_zones": {"columns": ["zone"], "data": []},
        "power_zones": {"columns": ["zone"], "data": []},
        "lap_count": 12,
    }

    actual = normalize_activity(activity)

    assert list(actual) == [
        "name", "activity_id", "type", "distance", "time", "elapsed_time", "moving_time",
        "avg_pace", "gap", "avg_hr", "max_hr", "recovery_hr", "elevation_gain", "elevation_loss",
        "load", "start_time_local", "training_effect", "interval_drift", "splits", "weather",
        "hr_zones", "power_zones", "lap_count",
    ]
    assert actual["time"] == "42:23"
    assert actual["elapsed_time"] == "50:07"
    assert actual["moving_time"] == "42:20"
    assert actual["training_effect"]["aerobic_message"] == "IMPROVING_VO2_MAX"
    assert actual["interval_drift"]["work_reps"] == 5
    assert "duration_min" not in actual
    assert "aerobic_te" not in actual
    assert "anaerobic_te" not in actual
    assert "training_effect_label" not in actual

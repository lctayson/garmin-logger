import json
from pathlib import Path

from run_garmin_to_json import _add_split_elapsed_times
from split_garmin_json import refresh_latest_activities


def read_latest(path):
    return json.loads((path / "latest_activities.json").read_text(encoding="utf-8"))


def test_split_elapsed_time_is_inserted_after_time():
    class FakeApi:
        def get_activity_splits(self, activity_id):
            return {"lapDTOs": [
                {"elapsedDuration": 601},
                {"elapsedDuration": 711},
            ]}

    activity = {
        "activityId": 123,
        "activity_splits": [
            {"step_type": "WARMUP", "lap": 1, "time": "10:01", "avg_pace": "7:23"},
            {"step_type": "ACTIVE", "lap": 2, "time": "1:50", "avg_pace": "17:26"},
        ],
    }

    _add_split_elapsed_times(FakeApi(), activity)
    rows = activity["activity_splits"]

    assert list(rows[0])[:4] == ["step_type", "lap", "time", "elapsed_time"]
    assert rows[0]["elapsed_time"] == "10:01"
    assert rows[1]["elapsed_time"] == "11:51"


def test_latest_activities_has_no_legacy_duration_fields():
    activity = read_latest(Path("data"))["activities"][0]
    assert "duration_min" not in activity
    assert "aerobic_te" not in activity
    assert "anaerobic_te" not in activity
    assert "training_effect_label" not in activity

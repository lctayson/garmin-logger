from run_garmin_to_json import _add_interval_drift


def split(step_type, seconds, pace="7:30", hr=140, power=240):
    return {
        "step_type": step_type,
        "time_seconds": seconds,
        "avg_pace": pace,
        "avg_hr": hr,
        "avg_power_w": power,
    }


def test_easy_run_with_strides_does_not_get_interval_drift():
    activity = {
        "type": "running",
        "activity_splits": [
            split("ACTIVE", 450, "7:30", 125, 225),
            split("ACTIVE", 440, "7:20", 140, 240),
            split("ACTIVE", 445, "7:25", 145, 240),
            split("ACTIVE", 446, "7:26", 147, 238),
            split("ACTIVE", 443, "7:23", 149, 238),
            split("ACTIVE", 15, "6:10", 153, 244),
            split("ACTIVE", 20, "5:23", 156, 275),
            split("RECOVERY", 90, "11:58", 145, 212),
            split("ACTIVE", 20, "5:00", 136, 189),
            split("RECOVERY", 90, "12:34", 139, 193),
        ],
    }

    _add_interval_drift(activity)

    assert "interval_drift" not in activity


def test_long_interval_workout_still_gets_interval_drift():
    activity = {
        "type": "running",
        "activity_splits": [
            split("ACTIVE", 600, "6:00", 150, 280),
            split("RECOVERY", 90, "10:00", 135, 190),
            split("ACTIVE", 600, "5:55", 154, 282),
            split("RECOVERY", 90, "10:00", 138, 190),
            split("ACTIVE", 600, "5:50", 158, 285),
        ],
    }

    _add_interval_drift(activity)

    assert activity["interval_drift"]["work_reps"] == 3

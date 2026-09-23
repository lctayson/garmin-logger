from run_garmin_to_json import _add_interval_drift


def split(step_type, seconds, pace="7:30", hr=140, power=240, step_index=None):
    row = {
        "step_type": step_type,
        "time_seconds": seconds,
        "avg_pace": pace,
        "avg_hr": hr,
        "avg_power_w": power,
    }
    if step_index is not None:
        row["workout_step_index"] = step_index
    return row


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


def test_short_reps_under_120s_still_get_interval_drift():
    """400m at sub-5:00/km is ~108-118s -- well under the old 120s floor --
    but it's genuine recovery-bounded interval work and should count."""
    activity = {
        "type": "running",
        "activity_splits": [
            split("WARMUP", 600, "7:30", 130, 200),
            split("ACTIVE", 118, "4:55", 158, 320),
            split("RECOVERY", 90, "9:00", 140, 190),
            split("ACTIVE", 112, "4:40", 163, 328),
            split("RECOVERY", 90, "9:00", 142, 190),
            split("ACTIVE", 108, "4:32", 168, 335),
            split("RECOVERY", 90, "9:00", 145, 190),
            split("ACTIVE", 105, "4:25", 172, 340),
            split("COOLDOWN", 600, "7:40", 135, 200),
        ],
    }

    _add_interval_drift(activity)

    assert activity["interval_drift"]["work_reps"] == 4


def test_workout_step_index_separates_short_warm_up_from_short_main_reps():
    """Warm-up strides and the main reps can both be under the old 60s
    duration-fallback bucket boundary (20s strides vs ~45s reps here), so
    duration alone can't tell them apart. workout_step_index should."""
    activity = {
        "type": "running",
        "activity_splits": [
            split("ACTIVE", 20, "5:05", 140, 230, step_index=1),
            split("RECOVERY", 60, "10:00", 120, 180, step_index=2),
            split("ACTIVE", 20, "5:00", 142, 232, step_index=1),
            split("RECOVERY", 60, "10:00", 120, 180, step_index=2),
            split("ACTIVE", 45, "3:50", 160, 300, step_index=3),
            split("RECOVERY", 75, "9:30", 138, 190, step_index=4),
            split("ACTIVE", 44, "3:45", 165, 305, step_index=3),
            split("RECOVERY", 75, "9:30", 140, 190, step_index=4),
            split("ACTIVE", 43, "3:41", 170, 310, step_index=3),
        ],
    }

    _add_interval_drift(activity)

    drift = activity["interval_drift"]
    # 3 main reps (step_index 3), not the 2 warm-up strides (step_index 1)
    assert drift["work_reps"] == 3
    assert drift["hr_delta_bpm"] == 10.0  # 170 - 160, not a warm-up value


def test_workout_step_index_prefers_larger_total_duration_group():
    """Mirrors a real threshold session: short warm-up strides plus longer
    main reps, both bounded by recovery -- the longer-total-duration group
    (the main reps) should win, matching what MS: reports."""
    activity = {
        "type": "running",
        "activity_splits": [
            split("WARMUP", 600, "7:40", 128, 200),
            split("ACTIVE", 20, "5:12", 159, 236, step_index=1),
            split("RECOVERY", 120, "10:00", 130, 180, step_index=2),
            split("ACTIVE", 20, "5:11", 164, 240, step_index=1),
            split("RECOVERY", 120, "10:00", 132, 180, step_index=2),
            split("ACTIVE", 335, "5:35", 155, 306, step_index=4),
            split("RECOVERY", 120, "10:00", 140, 190, step_index=5),
            split("ACTIVE", 323, "5:23", 162, 317, step_index=4),
            split("COOLDOWN", 600, "7:45", 130, 200),
        ],
    }

    _add_interval_drift(activity)

    drift = activity["interval_drift"]
    assert drift["work_reps"] == 2
    assert drift["hr_delta_bpm"] == 7.0  # 162 - 155, the threshold reps
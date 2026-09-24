from render_summary_md import _main_set_line

COLUMNS = [
    "step_type", "lap", "time", "avg_pace", "avg_hr", "distance",
    "stride_length", "avg_run_cadence", "avg_ground_contact_time",
    "avg_vertical_oscillation", "avg_power", "workout_step_index",
]


def row(step_type, seconds_str, avg_hr, distance, stride=0.78, cadence=172,
        gct=274, vosc=7.8, power=235, step_index=None):
    return [
        step_type, 1, seconds_str, "7:20", avg_hr, distance,
        stride, cadence, gct, vosc, power, step_index,
    ]


def activity(rows):
    return {"splits": {"columns": COLUMNS, "data": rows}}


def test_continuous_run_active_type_gets_whole_run_averages():
    """Plain continuous run, no strides, no recovery -- MS should be the
    whole run's averages, not None."""
    act = activity([
        row("ACTIVE", "7:29", 130, 1.00),
        row("ACTIVE", "7:13", 141, 1.00),
        row("ACTIVE", "7:08", 146, 1.00),
        row("ACTIVE", "7:17", 148, 1.00),
        row("ACTIVE", "7:20", 151, 1.00),
    ])

    line = _main_set_line(act)

    assert line is not None
    assert line.startswith("  - MS: 5.00k @")


def test_continuous_run_interval_type_gets_whole_run_averages():
    """Same as above, but Garmin tagged the laps 'INTERVAL' instead of
    'ACTIVE' -- this is the exact shape that was previously returning None
    (today's reported bug): a continuous run with no RECOVERY splits at
    all should still get an MS line, using every lap's averages."""
    act = activity([
        row("INTERVAL", "7:37", 131, 1.00),
        row("INTERVAL", "7:18", 140, 1.00),
        row("INTERVAL", "7:12", 144, 1.00),
        row("INTERVAL", "7:15", 147, 1.00),
        row("INTERVAL", "7:15", 148, 1.00),
        row("INTERVAL", "7:06", 151, 1.00),
    ])

    line = _main_set_line(act)

    assert line is not None
    assert line.startswith("  - MS: 6.00k @")
    assert "143bpm" in line  # time-weighted avg HR across all 6 laps


def test_easy_run_with_strides_still_excludes_strides_from_main_set():
    """Regression: a continuous main set followed by short recovery-bounded
    strides should still summarize only the main set, not the strides."""
    act = activity([
        row("ACTIVE", "7:29", 127, 1.02, step_index=0),
        row("ACTIVE", "7:13", 141, 0.99, step_index=0),
        row("ACTIVE", "7:08", 146, 1.01, step_index=0),
        row("ACTIVE", "7:17", 148, 1.00, step_index=0),
        row("ACTIVE", "7:20", 150, 1.00, step_index=0),
        row("ACTIVE", "0:20", 155, 0.09, step_index=1),
        row("RECOVERY", "1:30", 144, 0.12, step_index=2),
        row("ACTIVE", "0:20", 135, 0.09, step_index=1),
    ])

    line = _main_set_line(act)

    assert line is not None
    assert line.startswith("  - MS: 5.02k @")


def test_quality_day_picks_main_reps_over_warm_up_strides():
    """Regression: warm-up strides (short, step_index 1) ahead of the real
    quality reps (longer, step_index 4) should not be what MS reports."""
    act = activity([
        row("ACTIVE", "0:20", 159, 0.09, step_index=1),
        row("RECOVERY", "1:00", 130, 0.10, step_index=2),
        row("ACTIVE", "0:20", 164, 0.09, step_index=1),
        row("RECOVERY", "1:00", 132, 0.10, step_index=2),
        row("ACTIVE", "5:35", 155, 1.00, step_index=4),
        row("RECOVERY", "2:00", 140, 0.30, step_index=5),
        row("ACTIVE", "5:23", 162, 1.00, step_index=4),
    ])

    line = _main_set_line(act)

    assert line is not None
    assert line.startswith("  - MS: 2.00k @")
    assert "159bpm" not in line and "164bpm" not in line


def test_missing_required_columns_returns_none():
    act = {"splits": {"columns": ["step_type", "lap"], "data": [["ACTIVE", 1]]}}

    assert _main_set_line(act) is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))

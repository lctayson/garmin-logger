from garmin_activity_enrichment import _calculate_decoupling


def split(step_type, seconds, pace, hr, power=240):
    return {
        "step_type": step_type,
        "time_seconds": seconds,
        "avg_pace": pace,
        "avg_hr": hr,
        "avg_power_w": power,
    }


def test_pure_continuous_run_still_gets_decoupling():
    """No strides, no recovery -- baseline behaviour must be unchanged."""
    activity = {
        "type": "running",
        "activity_splits": [
            split("ACTIVE", 450, "7:29", 130, 225),
            split("ACTIVE", 440, "7:13", 141, 240),
            split("ACTIVE", 445, "7:08", 146, 245),
            split("ACTIVE", 446, "7:17", 148, 238),
            split("ACTIVE", 443, "7:20", 151, 236),
            split("ACTIVE", 450, "7:35", 153, 235),
        ],
    }

    _calculate_decoupling(activity)

    assert "decoupling" in activity
    assert "pace_pct" in activity["decoupling"]


def test_easy_run_with_strides_gets_decoupling_on_main_set_only():
    """Strides + walk recoveries tacked onto a continuous easy run shouldn't
    block decoupling entirely -- it should compute over the continuous main
    set and ignore the strides block, since that's the only genuinely
    continuous aerobic effort in the activity."""
    activity = {
        "type": "running",
        "activity_splits": [
            split("ACTIVE", 449, "7:29", 127, 225),
            split("ACTIVE", 433, "7:13", 141, 240),
            split("ACTIVE", 428, "7:08", 146, 245),
            split("ACTIVE", 437, "7:17", 148, 238),
            split("ACTIVE", 440, "7:20", 150, 236),
            split("ACTIVE", 10, "6:53", 152, 230),
            split("ACTIVE", 20, "5:02", 155, 236),
            split("RECOVERY", 90, "9:00", 144, 190),
            split("ACTIVE", 20, "4:52", 135, 232),
            split("RECOVERY", 90, "9:00", 138, 190),
            split("ACTIVE", 20, "4:44", 137, 240),
        ],
    }

    _calculate_decoupling(activity)

    assert "decoupling" in activity
    # sanity check: the number should be in the same ballpark as the
    # continuous-run case above (drift from HR climbing over an easy run),
    # not the wild swing a walk-recovery-contaminated calc would produce.
    assert 0 < activity["decoupling"]["pace_pct"] < 20


def test_short_stride_reps_alone_do_not_get_decoupling():
    """Warm-up strides and quality reps are each individually recovery-
    bounded -- no single contiguous segment is long enough (>= 3 splits) for
    a meaningful two-half comparison, so decoupling should stay absent and
    interval_drift remains the right metric for this shape."""
    activity = {
        "type": "running",
        "activity_splits": [
            split("WARMUP", 600, "7:40", 128),
            split("ACTIVE", 20, "5:12", 159, 236),
            split("RECOVERY", 120, "10:00", 130, 180),
            split("ACTIVE", 20, "5:11", 164, 240),
            split("RECOVERY", 120, "10:00", 132, 180),
            split("ACTIVE", 335, "5:35", 155, 306),
            split("RECOVERY", 120, "10:00", 140, 190),
            split("ACTIVE", 323, "5:23", 162, 317),
            split("COOLDOWN", 600, "7:45", 130),
        ],
    }

    _calculate_decoupling(activity)

    assert "decoupling" not in activity


def test_main_set_under_20_minutes_still_gets_no_decoupling():
    """The duration floor still applies to whichever segment gets picked --
    a short continuous main set ahead of strides shouldn't be decoupled
    just because it's the longest segment available."""
    activity = {
        "type": "running",
        "activity_splits": [
            split("ACTIVE", 300, "7:29", 130, 225),
            split("ACTIVE", 300, "7:20", 145, 236),
            split("ACTIVE", 300, "7:15", 150, 238),
            split("ACTIVE", 20, "5:02", 155, 236),
            split("RECOVERY", 90, "9:00", 144, 190),
            split("ACTIVE", 20, "4:52", 135, 232),
        ],
    }

    _calculate_decoupling(activity)

    assert "decoupling" not in activity


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))

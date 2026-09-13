"""
compact_metrics.py's `direct` tuple listed ("score","score"), ("level",
"level"), ("feedback_short","feedback") FIRST -- clearly intending the
headline score/level/feedback to appear first in the output readiness
dict. But that first loop reads from `daily` (daily_readiness's raw
dict), where those keys don't live -- they're nested one level down
under daily_readiness["readiness"]. So the first loop's checks for
those three always silently missed, and a second loop further down
(reading the correct nested dict) inserted them afterwards -- landing
score/level/feedback at the END of the output dict instead of the
front, even though the code's own ordering intended otherwise.

Field order in a JSON object has no semantic effect (dicts are
unordered), but it matters for a person reading the raw file, and
should match the code's evident original intent: score/level/feedback
as the headline, then the supporting raw metrics, then the detailed
factor breakdown last.
"""

from compact_metrics import compact_metrics


def _readiness_source(**readiness_overrides):
    readiness = {
        "score": 15,
        "level": "Poor",
        "feedback_short": "Find Time To Relax",
    }
    readiness.update(readiness_overrides)
    return {
        "date": "2026-09-08",
        "daily_readiness": {
            "resting_heart_rate": 57,
            "total_sleep_hours": 5.05,
            "sleep_score": 54,
            "recovery_time_hours": 26.4,
            "readiness": readiness,
        },
    }


def test_score_level_feedback_come_first():
    out = compact_metrics(_readiness_source())
    keys = list(out["readiness"].keys())
    assert keys[:3] == ["score", "level", "feedback"]


def test_factor_details_still_come_last():
    out = compact_metrics(
        _readiness_source(factors={"sleep_score": {"percent": 37, "feedback": "Poor"}})
    )
    keys = list(out["readiness"].keys())
    assert keys[-1] == "factor_details"
    assert keys[0] == "score"


def test_readiness_values_unchanged_by_reordering():
    """Regression: only order changed, not which values end up in the dict."""
    out = compact_metrics(_readiness_source())
    readiness = out["readiness"]
    assert readiness["score"] == 15
    assert readiness["level"] == "Poor"
    assert readiness["feedback"] == "Find Time To Relax"
    assert readiness["resting_hr"] == 57
    assert readiness["sleep_score"] == 54
    assert readiness["recovery_hours"] == 26.4


def test_missing_score_does_not_break_ordering_or_crash():
    """A day with no training-readiness score at all (e.g. API call failed)
    should just omit score/level/feedback, not crash or misorder the rest."""
    source = {
        "date": "2026-09-08",
        "daily_readiness": {
            "resting_heart_rate": 57,
            "sleep_score": 54,
        },
    }
    out = compact_metrics(source)
    readiness = out["readiness"]
    assert "score" not in readiness
    assert list(readiness.keys())[0] == "resting_hr"
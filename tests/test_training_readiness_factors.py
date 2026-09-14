"""
Garmin's Training Readiness score is built from six factors: Sleep Score,
Recovery Time, HRV Status, Acute Load, Recent Sleep Scores (sleep history),
and Recent Stress (stress history). get_training_readiness_details() was
only parsing five of them -- sleep_history was missing entirely, so
"Recent Sleep Scores" never showed up in daily_readiness.factor_details.

The raw camelCase field names (sleepHistoryFactorPercent /
sleepHistoryFactorFeedback) match the same "<Name>FactorPercent" /
"<Name>FactorFeedback" pattern used by the other five factors already
handled, confirmed against Garmin API response field names.
"""

from garmin_helpers import get_training_readiness_details


class FakeApi:
    """Returns a single training-readiness entry shaped like Garmin's real
    API response (all six factor pairs present, camelCase)."""

    def __init__(self, entry):
        self._entry = entry

    def get_training_readiness(self, date_str):
        return [self._entry]


FULL_ENTRY = {
    "timestamp": "2026-09-08T07:11:00",
    "score": 15,
    "level": "POOR",
    "feedbackShort": "FIND_TIME_TO_RELAX",
    "recoveryTime": 1380,  # minutes -> 23.0 hours
    "sleepScoreFactorPercent": 37,
    "sleepScoreFactorFeedback": "POOR",
    "sleepHistoryFactorPercent": 55,
    "sleepHistoryFactorFeedback": "FAIR",
    "recoveryTimeFactorPercent": 57,
    "recoveryTimeFactorFeedback": "MODERATE",
    "acwrFactorPercent": 90,
    "acwrFactorFeedback": "GOOD",
    "hrvFactorPercent": 93,
    "hrvFactorFeedback": "GOOD",
    "stressHistoryFactorPercent": 72,
    "stressHistoryFactorFeedback": "MEDIUM",
}


def test_sleep_history_factor_is_parsed():
    result = get_training_readiness_details(FakeApi(FULL_ENTRY), "2026-09-08")
    factors = result["readiness"]["factors"]
    assert factors["sleep_history"] == {"percent": 55, "feedback": "Fair"}


def test_all_six_readiness_factors_present():
    result = get_training_readiness_details(FakeApi(FULL_ENTRY), "2026-09-08")
    factors = result["readiness"]["factors"]
    assert set(factors.keys()) == {
        "sleep_score",
        "sleep_history",
        "recovery_time",
        "acwr",
        "hrv",
        "stress_history",
    }


def test_recovery_time_hours_still_computed_correctly():
    """Regression: adding sleep_history must not disturb the existing
    recovery_time_hours / other-factor parsing."""
    result = get_training_readiness_details(FakeApi(FULL_ENTRY), "2026-09-08")
    assert result["recovery_time_hours"] == 23.0
    factors = result["readiness"]["factors"]
    assert factors["sleep_score"] == {"percent": 37, "feedback": "Poor"}
    assert factors["recovery_time"] == {"percent": 57, "feedback": "Moderate"}
    assert factors["acwr"] == {"percent": 90, "feedback": "Good"}
    assert factors["hrv"] == {"percent": 93, "feedback": "Good"}
    assert factors["stress_history"] == {"percent": 72, "feedback": "Medium"}


def test_missing_sleep_history_field_is_simply_omitted():
    """If Garmin ever omits the field for a given entry, sleep_history
    should just be absent from factors (like the others), not raise."""
    entry = dict(FULL_ENTRY)
    del entry["sleepHistoryFactorPercent"]
    del entry["sleepHistoryFactorFeedback"]
    result = get_training_readiness_details(FakeApi(entry), "2026-09-08")
    assert "sleep_history" not in result["readiness"]["factors"]

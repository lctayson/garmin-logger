from garmin_helpers import get_training_readiness_details


class FakeApi:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def get_training_readiness(self, date_str):
        return self.snapshots


def test_morning_snapshot_wins_over_later_post_exercise_snapshot():
    snapshots = [
        {
            "timestamp": "2026-10-08T05:23:00",
            "inputContext": "AFTER_WAKEUP_RESET",
            "score": 72,
            "level": "RECOVERED_AND_READY",
            "feedbackShort": "RECOVERED_AND_READY",
            "recoveryTime": 1,
            "acuteLoad": 432,
            "sleepScoreFactorPercent": 74,
            "sleepScoreFactorFeedback": "GOOD",
            "recoveryTimeFactorPercent": 99,
            "recoveryTimeFactorFeedback": "GOOD",
            "acwrFactorPercent": 97,
            "acwrFactorFeedback": "GOOD",
            "inputContext": "AFTER_WAKEUP_RESET",
            "recoveryTimeChangePhrase": "NO_CHANGE_SLEEP",
        },
        {
            "timestamp": "2026-10-08T07:10:00",
            "inputContext": "AFTER_POST_EXERCISE_RESET",
            "score": 53,
            "level": "RECOVERY_IN_PROGRESS",
            "feedbackShort": "RECOVERY_IN_PROGRESS",
            "recoveryTime": 1584,
            "acuteLoad": 620,
            "sleepScoreFactorPercent": 74,
            "sleepScoreFactorFeedback": "GOOD",
            "recoveryTimeFactorPercent": 57,
            "recoveryTimeFactorFeedback": "MODERATE",
            "acwrFactorPercent": 85,
            "acwrFactorFeedback": "GOOD",
            "inputContext": "AFTER_POST_EXERCISE_RESET",
            "recoveryTimeChangePhrase": "REACHED_ZERO",
        },
    ]

    result = get_training_readiness_details(FakeApi(snapshots), "2026-10-08")

    assert result["readiness"]["score"] == 72
    assert result["readiness"]["level"] == "Recovered And Ready"
    assert result["recovery_time_hours"] == 0.0
    stored = result["readiness"]["snapshots"]
    assert [item["score"] for item in stored] == [72, 53]
    assert [item["context"] for item in stored] == ["AFTER_WAKEUP_RESET", "AFTER_POST_EXERCISE_RESET"]
    assert stored[0]["recovery_minutes"] == 1
    assert stored[1]["recovery_minutes"] == 1584
    assert stored[0]["acute_load"] == 432 and stored[1]["acute_load"] == 620
    assert stored[1]["factor_overrides"]["recovery_time"] == {"percent": 57, "feedback": "Moderate"}
    assert stored[1]["factor_overrides"]["acwr"] == {"percent": 85, "feedback": "Good"}
    assert "sleep_score" not in stored[1].get("factor_overrides", {})
    assert all("timestamp" not in item and "userProfilePK" not in item and "deviceId" not in item for item in stored)


def test_earliest_snapshot_is_fallback_when_context_is_missing():
    snapshots = [
        {"timestamp": "2026-10-08T07:10:00", "score": 53, "level": "RECOVERY_IN_PROGRESS"},
        {"timestamp": "2026-10-08T05:23:00", "score": 72, "level": "RECOVERED_AND_READY"},
    ]

    result = get_training_readiness_details(FakeApi(snapshots), "2026-10-08")

    assert result["readiness"]["score"] == 72

def test_snapshot_array_orders_morning_before_post_exercise_and_omits_for_single_reading():
    reversed_snapshots = [
        {
            "timestampLocal": "2026-10-08T07:10:48.0",
            "inputContext": "AFTER_POST_EXERCISE_RESET",
            "score": 53,
            "feedbackShort": "RECOVERY_IN_PROGRESS",
            "recoveryTime": 1584,
        },
        {
            "timestampLocal": "2026-10-08T05:23:16.0",
            "inputContext": "AFTER_WAKEUP_RESET",
            "score": 72,
            "feedbackShort": "RECOVERED_AND_READY",
            "recoveryTime": 1,
        },
    ]
    result = get_training_readiness_details(FakeApi(reversed_snapshots), "2026-10-08")
    assert [item["score"] for item in result["readiness"]["snapshots"]] == [72, 53]

    single = get_training_readiness_details(FakeApi([reversed_snapshots[1]]), "2026-10-08")
    assert "snapshots" not in single["readiness"]

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
            "recoveryTime": 300,
        },
        {
            "timestamp": "2026-10-08T07:10:00",
            "inputContext": "AFTER_POST_EXERCISE_RESET",
            "score": 53,
            "level": "RECOVERY_IN_PROGRESS",
            "feedbackShort": "RECOVERY_IN_PROGRESS",
            "recoveryTime": 1584,
        },
    ]

    result = get_training_readiness_details(FakeApi(snapshots), "2026-10-08")

    assert result["readiness"]["score"] == 72
    assert result["readiness"]["level"] == "Recovered And Ready"
    assert result["recovery_time_hours"] == 5.0


def test_earliest_snapshot_is_fallback_when_context_is_missing():
    snapshots = [
        {"timestamp": "2026-10-08T07:10:00", "score": 53, "level": "RECOVERY_IN_PROGRESS"},
        {"timestamp": "2026-10-08T05:23:00", "score": 72, "level": "RECOVERED_AND_READY"},
    ]

    result = get_training_readiness_details(FakeApi(snapshots), "2026-10-08")

    assert result["readiness"]["score"] == 72

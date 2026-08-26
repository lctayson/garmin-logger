from refresh_latest_activity import activity_date, get_latest_activity_payload


class FakeGarmin:
    def __init__(self, recent, formatted):
        self.recent = recent
        self.formatted = formatted

    def get_activities(self, start, limit):
        assert (start, limit) == (0, 1)
        return self.recent


def test_activity_date_uses_local_start_time():
    activity = {"startTimeLocal": "2026-08-26 06:15:00"}
    assert activity_date(activity) == "2026-08-26"


def test_latest_activity_uses_most_recent_garmin_activity(monkeypatch):
    api = FakeGarmin(
        [{"activityId": 2601, "startTimeLocal": "2026-08-26 06:15:00"}],
        None,
    )
    monkeypatch.setattr(
        "refresh_latest_activity.get_activities",
        lambda api, date: [{"activityId": 2601, "distance_km": 8.2}],
    )

    result = get_latest_activity_payload(api)

    assert result["date"] == "2026-08-26"
    assert result["activities"] == [{"activityId": 2601, "distance_km": 8.2}]


def test_historical_workflow_export_cannot_make_an_older_activity_latest(monkeypatch):
    api = FakeGarmin(
        [{"activityId": 2601, "startTimeLocal": "2026-08-26 06:15:00"}],
        None,
    )
    monkeypatch.setattr(
        "refresh_latest_activity.get_activities",
        lambda api, date: [{"activityId": 2601, "distance_km": 8.2}],
    )

    # The refresh source is Garmin's newest activity, not the date being exported.
    result = get_latest_activity_payload(api)
    assert result["date"] == "2026-08-26"
    assert result["activities"][0]["activityId"] == 2601

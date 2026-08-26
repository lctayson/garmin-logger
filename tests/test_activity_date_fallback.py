from datetime import datetime


def extract_date(value):
    if isinstance(value, str) and len(value) >= 10:
        try:
            datetime.strptime(value[:10], "%Y-%m-%d")
            return value[:10]
        except ValueError:
            return None
    return None


def fallback_by_date(exact_result, buffered_result, target_date):
    if exact_result:
        return exact_result
    out = []
    for activity in buffered_result:
        actual_date = (
            extract_date(activity.get("startTimeLocal"))
            or extract_date(activity.get("startTimeGMT"))
            or extract_date(activity.get("startTime"))
        )
        if actual_date == target_date:
            out.append(activity)
    return out


def test_exact_date_result_is_used():
    exact = [{"activityId": 100, "startTimeLocal": "2026-08-26T06:00:00"}]
    buffered = [{"activityId": 200, "startTimeLocal": "2026-08-26T07:00:00"}]
    result = fallback_by_date(exact, buffered, "2026-08-26")
    assert result == exact


def test_current_date_activity_is_recovered_when_exact_lookup_is_empty():
    buffered = [
        {"activityId": 100, "startTimeLocal": "2026-08-25T18:00:00"},
        {"activityId": 200, "startTimeLocal": "2026-08-26T06:00:00"},
        {"activityId": 300, "startTimeLocal": "2026-08-27T06:00:00"},
    ]
    result = fallback_by_date([], buffered, "2026-08-26")
    assert [x["activityId"] for x in result] == [200]


def test_historical_date_activity_is_recovered_without_adjacent_days():
    buffered = [
        {"activityId": 100, "startTimeLocal": "2026-08-12T18:00:00"},
        {"activityId": 200, "startTimeLocal": "2026-08-13T06:00:00"},
        {"activityId": 300, "startTimeLocal": "2026-08-14T06:00:00"},
    ]
    result = fallback_by_date([], buffered, "2026-08-13")
    assert [x["activityId"] for x in result] == [200]

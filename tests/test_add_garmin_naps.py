from datetime import date, datetime, timezone

from add_garmin_naps import collect_naps, nap_record


def test_nap_record_supports_garmin_epoch_timestamps_and_47_minutes():
    start = int(datetime(2026, 8, 25, 14, 10, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2026, 8, 25, 14, 57, tzinfo=timezone.utc).timestamp() * 1000)
    record = nap_record({
        "napStartTimestampLocal": start,
        "napEndTimestampLocal": end,
        "napTimeSeconds": 2820,
    })
    assert record["actual_date"] == "2026-08-25"
    assert record["duration_min"] == 47.0
    assert record["start"].startswith("2026-08-25T14:10:00")
    assert record["end"].startswith("2026-08-25T14:57:00")


def test_collect_naps_keeps_previous_day_nap_from_target_sleep_record_and_deduplicates():
    nap = {
        "napStartTimeLocal": "2026-08-25T14:10:00+08:00",
        "napEndTimeLocal": "2026-08-25T14:57:00+08:00",
        "napTimeSeconds": 2820,
    }

    class FakeGarmin:
        def __init__(self):
            self.calls = []

        def get_sleep_data(self, day):
            self.calls.append(day)
            if day == "2026-08-26":
                return {"dailySleepDTO": {"dailyNapDTOS": [nap]}}
            return {"dailySleepDTO": {"dailyNapDTOS": [nap]}}

    api = FakeGarmin()
    records = collect_naps(api, date(2026, 8, 26))

    assert api.calls == ["2026-08-26", "2026-08-25"]
    assert len(records) == 1
    assert records[0]["duration_min"] == 47.0
    assert records[0]["start"].startswith("2026-08-25T14:10:00")
    assert records[0]["end"].startswith("2026-08-25T14:57:00")


def test_collect_naps_does_not_accept_unrelated_date_from_previous_sleep_record():
    nap = {
        "napStartTimeLocal": "2026-08-24T14:10:00+08:00",
        "napEndTimeLocal": "2026-08-24T14:57:00+08:00",
        "napTimeSeconds": 2820,
    }

    class FakeGarmin:
        def get_sleep_data(self, day):
            if day == "2026-08-26":
                return {"dailySleepDTO": {"dailyNapDTOS": []}}
            return {"dailySleepDTO": {"dailyNapDTOS": [nap]}}

    assert collect_naps(FakeGarmin(), date(2026, 8, 26)) == []

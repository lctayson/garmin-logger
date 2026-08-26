from add_garmin_sleep_need import apply_sleep_need, extract_sleep_need, fetch_sleep_need


def test_extract_sleep_need_from_daily_sleep_dto():
    data = {
        "dailySleepDTO": {
            "sleepNeed": {
                "baseline": 470,
                "actual": 485,
                "feedback": "NO_CHANGE_NO_ADJUSTMENTS",
                "trainingFeedback": "INCREASED_TRAINING",
                "sleepHistoryAdjustment": "NO_CHANGE",
                "hrvAdjustment": "INCREASED",
                "napAdjustment": "DECREASED",
            },
            "nextSleepNeed": {"actual": 470},
        }
    }
    assert extract_sleep_need(data) == {
        "baseline_hours": 7.83,
        "need_hours": 8.08,
        "feedback": "No Change No Adjustments",
        "training_feedback": "Increased Training",
        "sleep_history_adjustment": "No Change",
        "hrv_adjustment": "Increased",
        "nap_adjustment": "Decreased",
        "next_need_hours": 7.83,
    }


def test_fetch_sleep_need_uses_sleep_service_endpoint():
    class FakeGarmin:
        def __init__(self):
            self.calls = []

        def connectapi(self, url, params=None):
            self.calls.append((url, params))
            return {"dailySleepDTO": {"sleepNeed": {"baseline": 470, "actual": 470}}}

    api = FakeGarmin()
    result = fetch_sleep_need(api, "2026-08-26")
    assert api.calls == [
        ("/sleep-service/sleep/dailySleepData", {"date": "2026-08-26", "nonSleepBufferMinutes": 60})
    ]
    assert result == {"baseline_hours": 7.83, "need_hours": 7.83}


def test_apply_sleep_need_keeps_daily_readiness_and_removes_stale_value():
    payload = {"date": "2026-08-26", "daily_readiness": {"sleep_need": {"need_hours": 6.0}}}
    result = apply_sleep_need(payload, None)
    assert "sleep_need" not in result["daily_readiness"]

    result = apply_sleep_need(payload, {"baseline_hours": 7.83, "need_hours": 8.08})
    assert result["daily_readiness"]["sleep_need"]["need_hours"] == 8.08

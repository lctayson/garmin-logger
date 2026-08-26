import importlib.util
import sys
import types
import unittest
from pathlib import Path


class FakeGarmin:
    _date_results = {}
    _calls = []

    def get_activities_by_date(self, start, end):
        self._calls.append((start, end))
        return list(self._date_results.get((start, end), []))

    def get_activity(self, activity_id):
        return {"activityId": activity_id}


class HistoricalActivityLookupTests(unittest.TestCase):
    def setUp(self):
        self.fake_garmin_module = types.ModuleType("garminconnect")
        self.fake_garmin_module.Garmin = FakeGarmin
        self.fake_helpers = types.ModuleType("garmin_helpers")
        self.fake_helpers.get_training_status_details = lambda *a, **k: {}
        self.fake_helpers.get_metric_trend = lambda *a, **k: []
        self.fake_helpers.get_body_battery_trend = lambda *a, **k: []
        self.fake_helpers.get_activities = lambda *a, **k: []
        sys.modules["garminconnect"] = self.fake_garmin_module
        sys.modules["garmin_helpers"] = self.fake_helpers
        FakeGarmin._date_results = {}
        FakeGarmin._calls = []

        path = Path(__file__).resolve().parents[1] / "sitecustomize.py"
        spec = importlib.util.spec_from_file_location("garmin_logger_sitecustomize_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.Garmin = FakeGarmin

    def test_exact_date_result_is_used_without_fallback(self):
        activity = {"activityId": 123, "startTimeLocal": "2026-08-13 06:00:00"}
        FakeGarmin._date_results[("2026-08-13", "2026-08-13")] = [activity]
        result = self.Garmin().get_activities_by_date("2026-08-13", "2026-08-13")
        self.assertEqual(result, [activity])
        self.assertEqual(FakeGarmin._calls, [("2026-08-13", "2026-08-13")])

    def test_empty_exact_date_uses_one_day_buffer_and_filters_actual_date(self):
        target = {"activityId": 456, "startTimeLocal": "2026-08-13 06:00:00"}
        adjacent = {"activityId": 789, "startTimeLocal": "2026-08-12 06:00:00"}
        FakeGarmin._date_results[("2026-08-13", "2026-08-13")] = []
        FakeGarmin._date_results[("2026-08-12", "2026-08-14")] = [adjacent, target]
        result = self.Garmin().get_activities_by_date("2026-08-13", "2026-08-13")
        self.assertEqual(result, [target])
        self.assertEqual(
            FakeGarmin._calls,
            [("2026-08-13", "2026-08-13"), ("2026-08-12", "2026-08-14")],
        )

    def test_no_activity_stays_empty(self):
        FakeGarmin._date_results[("2026-08-13", "2026-08-13")] = []
        FakeGarmin._date_results[("2026-08-12", "2026-08-14")] = []
        result = self.Garmin().get_activities_by_date("2026-08-13", "2026-08-13")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()

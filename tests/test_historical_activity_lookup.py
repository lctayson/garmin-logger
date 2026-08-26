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
        fake_garmin_module = types.ModuleType("garminconnect")
        fake_garmin_module.Garmin = FakeGarmin
        fake_helpers = types.ModuleType("garmin_helpers")
        fake_helpers.get_training_status_details = lambda *a, **k: {}
        fake_helpers.get_metric_trend = lambda *a, **k: []
        fake_helpers.get_body_battery_trend = lambda *a, **k: []
        fake_helpers.get_activities = lambda *a, **k: []
        sys.modules["garminconnect"] = fake_garmin_module
        sys.modules["garmin_helpers"] = fake_helpers
        FakeGarmin._date_results = {}
        FakeGarmin._calls = []

        path = Path(__file__).resolve().parents[1] / "sitecustomize.py"
        spec = importlib.util.spec_from_file_location("garmin_logger_sitecustomize_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

    def test_aug_9_exact_date_returns_half_marathon_activity(self):
        activity = {
            "activityId": 20260809,
            "startTimeLocal": "2026-08-09 05:10:00",
            "activityName": "Bulacan Marathon 21K",
        }
        FakeGarmin._date_results[("2026-08-09", "2026-08-09")] = [activity]

        result = FakeGarmin().get_activities_by_date("2026-08-09", "2026-08-09")

        self.assertEqual(result, [activity])
        self.assertEqual(FakeGarmin._calls, [("2026-08-09", "2026-08-09")])

    def test_exact_date_empty_stays_empty_and_does_not_query_adjacent_dates(self):
        FakeGarmin._date_results[("2026-08-09", "2026-08-09")] = []
        FakeGarmin._date_results[("2026-08-08", "2026-08-10")] = [
            {"activityId": 8, "startTimeLocal": "2026-08-08 06:00:00"},
            {"activityId": 9, "startTimeLocal": "2026-08-10 06:00:00"},
        ]

        result = FakeGarmin().get_activities_by_date("2026-08-09", "2026-08-09")

        self.assertEqual(result, [])
        self.assertEqual(FakeGarmin._calls, [("2026-08-09", "2026-08-09")])

    def test_non_exact_range_is_passed_through_unchanged(self):
        activities = [{"activityId": 1, "startTimeLocal": "2026-08-09 06:00:00"}]
        FakeGarmin._date_results[("2026-08-08", "2026-08-09")] = activities

        result = FakeGarmin().get_activities_by_date("2026-08-08", "2026-08-09")

        self.assertEqual(result, activities)
        self.assertEqual(FakeGarmin._calls, [("2026-08-08", "2026-08-09")])


if __name__ == "__main__":
    unittest.main()

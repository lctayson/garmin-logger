import importlib.util
import sys
import types
import unittest
from pathlib import Path


class FakeGarmin:
    def __init__(self):
        self.for_date_calls = []
        self.by_date_calls = []
        self.date_payload = []

    def get_activities_by_date(self, start, end):
        self.by_date_calls.append((start, end))
        return []

    def get_activities_fordate(self, date):
        self.for_date_calls.append(date)
        return self.date_payload


class ActivityExportDateEndpointTests(unittest.TestCase):
    def setUp(self):
        fake_helpers = types.ModuleType("garmin_helpers")
        fake_helpers.get_training_status_details = lambda *a, **k: {}
        fake_helpers.get_metric_trend = lambda *a, **k: []
        fake_helpers.get_body_battery_trend = lambda *a, **k: []

        def fake_get_activities(api, date):
            return api.get_activities_by_date(date, date)

        fake_helpers.get_activities = fake_get_activities
        fake_garmin = types.ModuleType("garminconnect")
        fake_garmin.Garmin = FakeGarmin
        sys.modules["garmin_helpers"] = fake_helpers
        sys.modules["garminconnect"] = fake_garmin

        path = Path(__file__).resolve().parents[1] / "sitecustomize.py"
        spec = importlib.util.spec_from_file_location("garmin_logger_sitecustomize_activity_test", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_aug_9_race_is_recovered_from_exact_date_endpoint(self):
        api = FakeGarmin()
        api.date_payload = [{
            "activityId": 123456789,
            "activityName": "Bulacan Marathon 21K",
            "startTimeLocal": "2026-08-09 05:10:00",
        }]

        result = self.module._get_activities_for_export(api, "2026-08-09")

        self.assertEqual(result, api.date_payload)
        self.assertEqual(api.by_date_calls, [("2026-08-09", "2026-08-09")])
        self.assertEqual(api.for_date_calls, ["2026-08-09"])

    def test_current_date_uses_exact_date_only(self):
        api = FakeGarmin()
        api.date_payload = [{
            "activityId": 987654321,
            "activityName": "Morning Run",
            "startTimeLocal": "2026-08-26 06:00:00",
        }]

        result = self.module._get_activities_for_export(api, "2026-08-26")

        self.assertEqual(result, api.date_payload)
        self.assertEqual(api.for_date_calls, ["2026-08-26"])
        self.assertNotIn(("2026-08-25", "2026-08-27"), api.by_date_calls)

    def test_no_activity_stays_empty(self):
        api = FakeGarmin()
        result = self.module._get_activities_for_export(api, "2026-08-26")

        self.assertEqual(result, [])
        self.assertEqual(api.for_date_calls, ["2026-08-26"])


if __name__ == "__main__":
    unittest.main()

import datetime as dt
import unittest

import run_garmin_to_json


class ActivityExportDateTests(unittest.TestCase):
    def test_date_object_is_normalized_to_garmin_date_string(self):
        calls = []

        def fake_get_activities(api, value):
            calls.append(value)
            return [{"activityId": 123, "type": "running"}]

        original = run_garmin_to_json._original_get_activities
        run_garmin_to_json._original_get_activities = fake_get_activities
        try:
            result = run_garmin_to_json.get_activities(object(), dt.date(2026, 8, 26))
        finally:
            run_garmin_to_json._original_get_activities = original

        self.assertEqual(calls, ["2026-08-26"])
        self.assertEqual([a.get("activity_id") for a in result], [123])


if __name__ == "__main__":
    unittest.main()
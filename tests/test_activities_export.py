import sys
import types
import unittest
from datetime import date

# Keep this test independent of Garmin authentication and the live API.
try:
    import garminconnect  # noqa: F401
except ImportError:
    fake_garminconnect = types.ModuleType("garminconnect")
    fake_garminconnect.Garmin = object
    sys.modules["garminconnect"] = fake_garminconnect

import garmin_helpers


class FakeGarmin:
    def __init__(self, activities):
        self.activities = activities
        self.calls = []

    def get_activities_by_date(self, start, end):
        self.calls.append((start, end))
        return self.activities

    def get_activity_splits(self, activity_id):
        return {
            "lapDTOs": [
                {
                    "lapIndex": 1,
                    "distance": 1000.0,
                    "duration": 360.0,
                    "averageHR": 150,
                    "averageRunCadence": 180,
                }
            ]
        }


class ActivitiesExportTests(unittest.TestCase):
    def test_aug_9_2026_half_marathon_is_exported(self):
        race = {
            "activityId": 9001,
            "activityName": "Bulacan Marathon 21K",
            "startTimeLocal": "2026-08-09 05:00:00",
            "activityType": {"typeKey": "running"},
            "distance": 21323.0,
            "duration": 8363.4,
            "averageHR": 163,
            "maxHR": 170,
            "aerobicTrainingEffect": 5.0,
            "exerciseLoad": 403,
        }
        api = FakeGarmin([race])

        result = garmin_helpers.get_activities(api, "2026-08-09")

        self.assertEqual(api.calls, [("2026-08-09", "2026-08-09")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["activityId"], 9001)
        self.assertEqual(result[0]["name"], "Bulacan Marathon 21K")
        self.assertAlmostEqual(result[0]["distance_km"], 21.32, places=2)
        self.assertIn("activity_splits", result[0])
        self.assertEqual(result[0]["activity_splits"][0]["lap"], 1)

    def test_no_activity_keeps_exact_date_query_and_returns_empty(self):
        api = FakeGarmin([])

        result = garmin_helpers.get_activities(api, "2026-08-26")

        self.assertEqual(result, [])
        self.assertEqual(api.calls, [("2026-08-26", "2026-08-26")])


if __name__ == "__main__":
    unittest.main()

import unittest

from activity_zones import add_activity_zones, compact_zones


class FakeGarmin:
    def __init__(self):
        self.hr_calls = []
        self.power_calls = []

    def get_activity_hr_in_timezones(self, activity_id):
        self.hr_calls.append(activity_id)
        return {"timeInZones": [
            {"zoneNumber": 1, "secsInZone": 780, "zoneLowBoundary": 110, "zoneDescription": "Warm Up"},
            {"zoneNumber": 2, "secsInZone": 420, "zoneLowBoundary": 146},
            {"zoneNumber": 3, "secsInZone": 720, "zoneLowBoundary": 153},
            {"zoneNumber": 4, "secsInZone": 360, "zoneLowBoundary": 164},
            {"zoneNumber": 5, "secsInZone": 100, "zoneLowBoundary": 170},
        ]}

    def get_activity_power_in_timezones(self, activity_id):
        self.power_calls.append(activity_id)
        return {"timeInZones": [
            {"zoneNumber": 1, "secsInZone": 934, "zoneLowBoundary": 196},
            {"zoneNumber": 2, "secsInZone": 346, "zoneLowBoundary": 241},
            {"zoneNumber": 3, "secsInZone": 383, "zoneLowBoundary": 272},
            {"zoneNumber": 4, "secsInZone": 625, "zoneLowBoundary": 301},
            {"zoneNumber": 5, "secsInZone": 0, "zoneLowBoundary": 347},
        ]}


class ActivityZoneTests(unittest.TestCase):
    def test_compact_zones_derives_ranges_from_garmin_lower_boundaries(self):
        payload = [
            {"zoneNumber": 1, "secsInZone": 60, "zoneLowBoundary": 110, "zoneDescription": "Warm Up"},
            {"zoneNumber": 2, "secsInZone": 120, "zoneLowBoundary": 146},
            {"zoneNumber": 3, "secsInZone": 60, "zoneLowBoundary": 153},
            {"zoneNumber": 4, "secsInZone": 0, "zoneLowBoundary": 164},
            {"zoneNumber": 5, "secsInZone": 0, "zoneLowBoundary": 170},
        ]
        self.assertEqual(
            compact_zones(payload, "hr"),
            {
                "columns": ["zone", "range", "time", "percent"],
                "data": [
                    ["Zone 1 - Warm Up", "110-145 bpm", "1:00", 25],
                    ["Zone 2", "146-152 bpm", "2:00", 50],
                    ["Zone 3", "153-163 bpm", "1:00", 25],
                    ["Zone 4", "164-169 bpm", "0:00", 0],
                    ["Zone 5", ">169 bpm", "0:00", 0],
                ],
            },
        )

    def test_add_activity_zones_adds_hr_and_power_without_removing_existing_data(self):
        api = FakeGarmin()
        activities = [{"activityId": 123, "name": "Morning Run", "distance_km": 6.06}]

        result = add_activity_zones(api, activities)

        self.assertEqual(result[0]["name"], "Morning Run")
        self.assertEqual(result[0]["distance_km"], 6.06)
        self.assertEqual(result[0]["hr_zones"]["data"][0], ["Zone 1 - Warm Up", "110-145 bpm", "13:00", 33])
        self.assertEqual(result[0]["power_zones"]["data"][3], ["Zone 4", "301-346 W", "10:25", 27])
        self.assertEqual(api.hr_calls, [123])
        self.assertEqual(api.power_calls, [123])

    def test_endpoint_failure_does_not_break_activity_export(self):
        class BrokenApi:
            def get_activity_hr_in_timezones(self, activity_id):
                raise RuntimeError("no HR zone data")

            def get_activity_power_in_timezones(self, activity_id):
                raise RuntimeError("no power zone data")

        activity = {"activityId": 456, "name": "Easy Run"}
        result = add_activity_zones(BrokenApi(), [activity])
        self.assertEqual(result, [activity])


if __name__ == "__main__":
    unittest.main()

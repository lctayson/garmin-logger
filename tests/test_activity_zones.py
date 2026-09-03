import unittest

from activity_zones import add_activity_zones, compact_zones


class FakeGarmin:
    def __init__(self):
        self.hr_calls = []
        self.power_calls = []

    def get_activity_hr_in_timezones(self, activity_id):
        self.hr_calls.append(activity_id)
        return {"timeInZones": [
            {"zoneNumber": 1, "secsInZone": 780},
            {"zoneNumber": 2, "secsInZone": 420},
            {"zoneNumber": 3, "secsInZone": 720},
            {"zoneNumber": 4, "secsInZone": 360},
            {"zoneNumber": 5, "secsInZone": 100},
        ]}

    def get_activity_power_in_timezones(self, activity_id):
        self.power_calls.append(activity_id)
        return {"timeInZones": [
            {"zoneNumber": 1, "secsInZone": 934},
            {"zoneNumber": 2, "secsInZone": 346},
            {"zoneNumber": 3, "secsInZone": 383},
            {"zoneNumber": 4, "secsInZone": 625},
            {"zoneNumber": 5, "secsInZone": 0},
        ]}


class ActivityZoneTests(unittest.TestCase):
    def test_compact_zones_uses_columns_and_data(self):
        payload = [
            {"zoneNumber": 1, "secsInZone": 60},
            {"zoneNumber": 2, "secsInZone": 120},
            {"zoneNumber": 3, "secsInZone": 60},
            {"zoneNumber": 4, "secsInZone": 0},
            {"zoneNumber": 5, "secsInZone": 0},
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
        self.assertEqual(
            result[0]["hr_zones"],
            {
                "columns": ["zone", "range", "time", "percent"],
                "data": [
                    ["Zone 1 - Warm Up", "110-145 bpm", "13:00", 33],
                    ["Zone 2", "146-152 bpm", "7:00", 18],
                    ["Zone 3", "153-163 bpm", "12:00", 30],
                    ["Zone 4", "164-169 bpm", "6:00", 15],
                    ["Zone 5", ">169 bpm", "1:40", 4],
                ],
            },
        )
        self.assertEqual(
            result[0]["power_zones"],
            {
                "columns": ["zone", "range", "time", "percent"],
                "data": [
                    ["Zone 1", "196-240 W", "15:34", 41],
                    ["Zone 2", "241-271 W", "5:46", 15],
                    ["Zone 3", "272-300 W", "6:23", 17],
                    ["Zone 4", "301-346 W", "10:25", 27],
                    ["Zone 5", ">346 W", "0:00", 0],
                ],
            },
        )
        self.assertEqual(api.hr_calls, [123])
        self.assertEqual(api.power_calls, [123])

    def test_garmin_boundaries_are_used_when_present(self):
        payload = {
            "timeInZones": [
                {"zoneNumber": 1, "secsInZone": 60, "zoneLowBoundary": 100, "zoneHighBoundary": 139},
                {"zoneNumber": 5, "secsInZone": 60, "zoneLowBoundary": 180},
            ]
        }
        result = compact_zones(payload, "hr")
        self.assertEqual(result["data"][0][1], "100-139 bpm")
        self.assertEqual(result["data"][4][1], ">179 bpm")

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

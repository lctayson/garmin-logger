import datetime as dt
import importlib.util
import sys
import types
import unittest
from pathlib import Path


class ActivityExportDateTests(unittest.TestCase):
    def test_date_object_is_normalized_to_garmin_date_string(self):
        calls = []
        fake_generator = types.ModuleType("garmin_to_json")
        fake_generator.get_activities = lambda api, value: calls.append(value) or [{"activityId": 123}]
        fake_generator.deep_get = lambda *args: ""
        fake_generator._history_distance_km = lambda act: 0
        fake_generator._history_duration_hours = lambda act: 0
        fake_generator._history_load = lambda act: None
        fake_generator._history_expand_multisport = lambda api, acts: acts
        fake_generator._history_date = lambda act, fallback: fallback
        sys.modules["garmin_to_json"] = fake_generator

        path = Path(__file__).resolve().parents[1] / "run_garmin_to_json.py"
        spec = importlib.util.spec_from_file_location("run_garmin_to_json_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        result = module.get_activities(object(), dt.date(2026, 8, 26))

        self.assertEqual(result, [{"activityId": 123}])
        self.assertEqual(calls, ["2026-08-26"])


if __name__ == "__main__":
    unittest.main()

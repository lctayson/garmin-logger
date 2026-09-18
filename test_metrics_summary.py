import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metrics_summary import attach_summary, build_summary
from render_summary_md import render


def _payload(**overrides):
    base = {
        "date": "2026-09-17",
        "readiness": {
            "score": 50,
            "level": "Moderate",
            "feedback": "Listen To Your Body",
            "resting_hr": 58,
            "hrv_last_night_avg_ms": 46.0,
            "hrv_7_day_avg_ms": 50.0,
            "sleep_hours": 6.1,
            "sleep_score": 76,
            "hrv_baseline": {"lowUpper": 45.0, "balancedLow": 47.0, "balancedUpper": 55.0},
            "factor_details": {
                "sleep_score": {"percent": 64, "feedback": "Moderate"},
                "hrv": {"percent": 100, "feedback": "Very Good"},
                "stress_history": {"percent": 52, "feedback": "Moderate"},
            },
        },
        "sleep": {"need_h": 7.0},
        "load": {"acwr": 1.0, "acwr_status": "Optimal", "training_status": "Maintaining 2"},
        "load_balance": {
            "aerobic_low": 516.6,
            "aerobic_low_target": [303, 822],
            "aerobic_high": 1541.9,
            "aerobic_high_target": [649, 1169],
            "anaerobic": 67.0,
            "anaerobic_target": [173, 519],
            "load_focus": "Anaerobic Shortage",
        },
        "running_tolerance": {"percent_of_tolerance": 66.1, "status": "Medium"},
        "training_history": {
            "7_day": {"total_endurance": {"distance": 34.21}},
            "28_day": {"avg_weekly_running_distance": 32.7},
        },
        "trend_recent_daily": {
            "columns": ["date", "resting_hr", "hrv_last_night_avg_ms", "sleep_hours"],
            "data": [
                ["2026-09-11", 61, 39.0, 4.27],
                ["2026-09-12", 59, 51.0, 7.92],
                ["2026-09-13", 58, 52.0, 6.25],
                ["2026-09-14", 57, 55.0, 6.77],
                ["2026-09-15", 57, 57.0, 6.40],
                ["2026-09-16", 58, 46.0, 6.10],
            ],
        },
    }
    base.update(overrides)
    return base


class BuildSummaryTests(unittest.TestCase):
    def test_limiting_factor_is_lowest_scoring(self):
        s = build_summary(_payload())["readiness"]
        self.assertEqual(s["limiting_factor"], "stress_history")
        self.assertEqual(s["limiting_factor_percent"], 52)

    def test_soft_factors_listed_strongest_separately(self):
        s = build_summary(_payload())["readiness"]
        self.assertIn("sleep_score", s["limiting_factors"])
        self.assertNotIn("hrv", s["limiting_factors"])
        self.assertEqual(s["strongest_factors"], ["hrv"])

    def test_load_balance_gaps_signed_and_stated(self):
        gaps = build_summary(_payload())["load"]["load_balance_gaps"]
        self.assertEqual(gaps["aerobic_low"], {"gap": 0, "state": "in_target"})
        self.assertEqual(gaps["anaerobic"]["state"], "below_target")
        self.assertEqual(gaps["anaerobic"]["gap"], -106.0)
        self.assertEqual(gaps["aerobic_high"]["state"], "above_target")
        self.assertGreater(gaps["aerobic_high"]["gap"], 0)

    def test_hrv_band_compares_value_not_status_label(self):
        # 46ms sits under the 47ms balanced floor even when Garmin's own
        # status string still reads BALANCED -- the value must win.
        payload = _payload()
        payload["readiness"]["hrv_status"] = "BALANCED"
        s = build_summary(payload)["recovery_trends"]
        self.assertEqual(s["hrv_vs_balanced_band"], "below")

    def test_hrv_band_within(self):
        payload = _payload()
        payload["readiness"]["hrv_last_night_avg_ms"] = 51.0
        self.assertEqual(build_summary(payload)["recovery_trends"]["hrv_vs_balanced_band"], "within")

    def test_sleep_nights_below_need_counted(self):
        s = build_summary(_payload())["recovery_trends"]
        self.assertEqual(s["sleep_need_h"], 7.0)
        self.assertEqual(s["sleep_nights_below_need"], 5)

    def test_volume_delta_vs_28d_average(self):
        v = build_summary(_payload())["volume"]
        self.assertEqual(v["distance_7d_km"], 34.21)
        self.assertAlmostEqual(v["distance_7d_vs_28d_avg_pct"], 4.6, places=1)

    def test_empty_payload_is_safe(self):
        self.assertEqual(build_summary({}), {"schema_version": 1})

    def test_missing_sections_are_omitted_not_null(self):
        summary = build_summary({"date": "2026-01-01"})
        self.assertNotIn("readiness", summary)
        self.assertNotIn("load", summary)

    def test_non_dict_rejected(self):
        with self.assertRaises(TypeError):
            build_summary([])


class AttachSummaryTests(unittest.TestCase):
    def test_summary_inserted_after_date(self):
        out = attach_summary(_payload())
        self.assertEqual(list(out.keys())[:2], ["date", "summary"])

    def test_original_keys_preserved(self):
        payload = _payload()
        out = attach_summary(payload)
        for key in payload:
            self.assertIn(key, out)
        self.assertEqual(out["load_balance"], payload["load_balance"])

    def test_idempotent(self):
        once = attach_summary(_payload())
        twice = attach_summary(once)
        self.assertEqual(json.dumps(once, sort_keys=True), json.dumps(twice, sort_keys=True))


class RenderTests(unittest.TestCase):
    def test_renders_headline_and_limiter(self):
        text = render(_payload(), None)
        self.assertIn("Readiness: 50/100", text)
        self.assertIn("Stress History", text)

    def test_flags_hrv_below_band(self):
        self.assertIn("below balanced band", render(_payload(), None))

    def test_activity_details_rendered_when_dated_today(self):
        payload = _payload()  # date: 2026-09-17
        activities = {
            "date": "2026-09-17",
            "activities": [
                {
                    "name": "2 x 7min Threshold",
                    "distance": 6.03,
                    "time": "40:35",
                    "avg_pace": "6:44",
                    "avg_hr": 147.0,
                    "max_hr": 168,
                    "training_effect": {"label": "TEMPO", "aerobic": 3.4, "anaerobic": 0.0},
                    "interval_drift": {"work_reps": 2, "pace_ef_drift_pct": -0.8, "hr_delta_bpm": 7.0},
                }
            ],
        }
        text = render(payload, activities)
        self.assertIn("## Today", text)
        self.assertNotIn("Rest Day", text)
        self.assertIn("2 x 7min Threshold", text)
        self.assertIn("TEMPO", text)
        self.assertIn("2 work reps", text)

    def test_stale_activity_file_labeled_as_rest_day_not_today(self):
        # Rest day: metrics date is newer than the activities file's date,
        # meaning split_garmin_json.py correctly did not refresh it. The
        # renderer must not present yesterday's run as today's.
        payload = _payload()
        payload["date"] = "2026-09-18"
        activities = {
            "date": "2026-09-17",
            "activities": [{"name": "Yesterday's Run", "distance": 6.03}],
        }
        text = render(payload, activities)
        self.assertIn("Rest Day", text)
        self.assertIn("Most recent activity (2026-09-17)", text)
        self.assertIn("Yesterday's Run", text)
        self.assertNotIn("## Today\n", text)

    def test_genuine_rest_day_with_no_activities_at_all(self):
        payload = _payload()
        text = render(payload, {"date": "2026-09-17", "activities": []})
        self.assertIn("Rest Day", text)
        self.assertIn("No activity logged", text)

    def test_missing_activity_file_is_distinguished_from_rest_day(self):
        self.assertIn("No activity file found", render(_payload(), None))
        self.assertNotIn("Rest Day", render(_payload(), None))

    def test_render_works_without_precomputed_summary(self):
        payload = _payload()
        self.assertNotIn("summary", payload)
        self.assertIn("Readiness: 50/100", render(payload, None))

    def test_no_triple_blank_lines(self):
        text = render(_payload(), {"date": "2026-09-17", "activities": []})
        self.assertNotIn("\n\n\n", text)


if __name__ == "__main__":
    unittest.main()

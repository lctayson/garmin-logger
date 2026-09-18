import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metrics_summary import attach_summary, build_summary
from render_summary_md import _main_set_line, render


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


class MainSetTests(unittest.TestCase):
    def _splits(self, columns, data):
        return {"splits": {"columns": columns, "data": data}}

    def test_matches_manually_verified_threshold_session(self):
        # Sept 17 real session: 3x20s strides (step_index 1) then 2x7min
        # threshold reps (step_index 4). Expected values hand-verified.
        columns = [
            "step_type", "lap", "time", "elapsed_time", "avg_pace", "avg_gap",
            "avg_hr", "max_hr", "start_hr", "min_hr", "end_hr", "avg_run_cadence",
            "best_pace", "max_run_cadence", "moving_time", "avg_moving_pace",
            "distance", "elevation_gain", "elevation_loss", "stride_length",
            "avg_vertical_oscillation", "avg_ground_contact_time",
            "normalized_power", "avg_power", "max_power", "avg_vertical_ratio",
            "workout_step_index", "workout_compliance_pct",
        ]
        data = [
            ["WARMUP", 1, "10:00", "10:00", "7:43", "7:47", 132.0, 138.0, 108, 108, 138, 172.0, "6:47", 179.0, "10:00", "7:43", 1.3, 0.0, 1.0, 0.75, 7.5, 274.9, 227.0, 226.0, 293.0, 10.0, 0, 100],
            ["ACTIVE", 2, "0:20", "0:20", "5:08", "5:20", 141.0, 144.0, 138, 138, 144, 184.0, "5:01", 188.0, "0:20", "5:08", 0.07, 0.0, 0.0, 1.01, 8.0, 239.6, 264.0, 323.0, 367.0, 7.9, 1, 100],
            ["RECOVERY", 3, "1:00", "1:00", "8:36", "8:13", 142.0, 145.0, 144, 139, 139, 167.0, "5:19", 185.0, "1:00", "8:36", 0.12, 0.0, 0.0, 0.73, 7.6, 285.5, 255.0, 215.0, 314.0, 10.5, 2, 100],
            ["ACTIVE", 4, "0:20", "0:20", "5:08", "5:36", 140.0, 143.0, 139, 138, 143, 182.0, "4:50", 188.0, "0:20", "5:08", 0.06, 0.0, 0.0, 0.97, 7.9, 245.1, 234.0, 310.0, 374.0, 8.3, 1, 100],
            ["RECOVERY", 5, "1:00", "1:00", "7:49", "7:33", 142.0, 145.0, 143, 140, 140, 171.0, "5:08", 186.0, "1:00", "7:49", 0.13, 0.0, 0.0, 0.77, 7.7, 276.0, 260.0, 232.0, 345.0, 10.0, 2, 100],
            ["ACTIVE", 6, "0:20", "0:20", "5:15", "5:45", 141.0, 143.0, 140, 139, 143, 182.0, "5:03", 187.0, "0:20", "5:15", 0.06, 0.0, 0.0, 0.96, 7.9, 246.0, 246.0, 301.0, 356.0, 8.3, 1, 100],
            ["RECOVERY", 7, "1:00", "1:00", "8:51", "8:40", 141.0, 144.0, 143, 135, 136, 145.0, "5:18", 187.0, "1:00", "8:51", 0.11, 0.0, 0.0, 0.82, 7.1, 271.1, 244.0, 184.0, 311.0, 9.4, 2, 100],
            ["ACTIVE", 8, "7:00", "7:00", "5:35", "5:34", 155.0, 160.0, 136, 136, 159, 182.0, "5:11", 186.0, "7:00", "5:35", 1.25, 1.0, 1.0, 0.98, 8.0, 244.2, 304.0, 306.0, 362.0, 8.1, 4, 100],
            ["RECOVERY", 9, "2:00", "2:00", "8:23", "8:17", 150.0, 160.0, 159, 144, 145, 165.0, "5:45", 178.0, "2:00", "8:22", 0.24, 0.0, 0.0, 0.74, 7.7, 288.5, 233.0, 216.0, 290.0, 10.5, 5, 100],
            ["ACTIVE", 10, "7:00", "7:00", "5:23", "5:25", 162.0, 168.0, 145, 145, 168, 182.0, "5:05", 186.0, "7:00", "5:23", 1.3, 1.0, 0.0, 1.01, 8.1, 242.2, 315.0, 317.0, 349.0, 8.0, 4, 100],
            ["COOLDOWN", 11, "10:35", "10:35", "7:36", "7:35", 149.0, 168.0, 168, 143, 150, 164.0, "5:05", 181.0, "10:35", "7:36", 1.39, 2.0, 1.0, 0.8, 7.7, 275.8, 239.0, 228.0, 336.0, 9.7, 7, None],
        ]
        act = self._splits(columns, data)
        self.assertEqual(
            _main_set_line(act),
            "  - MS: 2.55k @ 5:29 159bpm 1.00m 182spm 243ms 8.1cm 312w",
        )

    def test_falls_back_to_duration_threshold_without_step_index(self):
        columns = ["step_type", "time", "distance", "avg_hr", "avg_run_cadence",
                   "stride_length", "avg_ground_contact_time", "avg_vertical_oscillation", "avg_power"]
        data = [
            ["WARMUP", "5:00", 0.7, 130, 170, 0.8, 280, 7.5, 200],
            ["ACTIVE", "0:20", 0.1, 140, 184, 1.0, 240, 8.0, 260],
            ["RECOVERY", "1:00", 0.15, 142, 167, 0.75, 285, 7.6, 255],
            ["ACTIVE", "3:00", 0.6, 160, 182, 1.0, 244, 8.1, 310],
            ["RECOVERY", "2:00", 0.3, 150, 165, 0.8, 270, 7.7, 250],
            ["ACTIVE", "3:00", 0.62, 165, 183, 1.02, 242, 8.0, 318],
        ]
        result = _main_set_line(self._splits(columns, data))
        self.assertIsNotNone(result)
        self.assertIn("1.22k", result)
        self.assertNotIn("0.1", result)  # the 20s stride's distance must not leak into the total

    def test_none_for_continuous_run_without_intervals(self):
        act = self._splits(["step_type", "time", "distance"], [["ACTIVE", "30:00", 6.0]])
        self.assertIsNone(_main_set_line(act))

    def test_none_when_splits_missing(self):
        self.assertIsNone(_main_set_line({}))
        self.assertIsNone(_main_set_line({"splits": "not a dict"}))

    def test_none_when_single_active_group_only(self):
        # RECOVERY present but every ACTIVE row shares one step_index/duration
        # bucket -- nothing to separate from, so no MS line.
        columns = ["step_type", "time", "distance", "workout_step_index"]
        data = [
            ["ACTIVE", "5:00", 1.0, 4],
            ["RECOVERY", "1:00", 0.1, 5],
            ["ACTIVE", "5:00", 1.0, 4],
        ]
        self.assertIsNone(_main_set_line(self._splits(columns, data)))

    def test_appears_in_full_activity_render(self):
        act = {
            "name": "Test Session",
            "distance": 6.0,
            "splits": self._splits(
                ["step_type", "time", "distance", "avg_hr", "avg_run_cadence",
                 "stride_length", "avg_ground_contact_time", "avg_vertical_oscillation", "avg_power"],
                [
                    ["ACTIVE", "0:20", 0.1, 140, 184, 1.0, 240, 8.0, 260],
                    ["RECOVERY", "1:00", 0.15, 142, 167, 0.75, 285, 7.6, 255],
                    ["ACTIVE", "3:00", 0.6, 160, 182, 1.0, 244, 8.1, 310],
                ],
            )["splits"],
        }
        text = render(_payload(), {"date": "2026-09-17", "activities": [act]})
        self.assertIn("MS:", text)


class ThisWeekTests(unittest.TestCase):
    def test_rest_and_activity_days_labeled(self):
        payload = _payload()
        payload["trend_recent_daily"] = {
            "columns": ["date", "activity_count", "distance", "sport_volume", "exercise_load"],
            "data": [
                ["2026-09-11", 0, 0.0, {}, None],
                ["2026-09-12", 1, 10.03, {"running": {}}, 177.4],
            ],
        }
        text = render(payload, None)
        self.assertIn("## This Week", text)
        self.assertIn("Fri Sep 11 — rest", text)
        self.assertIn("Sat Sep 12 — running, 10.03km, load 177.4", text)

    def test_omitted_when_no_trend_data(self):
        payload = _payload()
        payload.pop("trend_recent_daily", None)
        self.assertNotIn("## This Week", render(payload, None))

    def test_multi_sport_day_joins_sport_names(self):
        payload = _payload()
        payload["trend_recent_daily"] = {
            "columns": ["date", "activity_count", "distance", "sport_volume", "exercise_load"],
            "data": [["2026-09-12", 2, 4.0, {"running": {}, "cycling": {}}, 90.0]],
        }
        text = render(payload, None)
        self.assertIn("running/cycling", text)


    def test_load_lines_show_raw_source_values(self):
        payload = _payload()
        payload["load"]["acute_load"] = 491
        payload["load"]["chronic_load"] = 541
        payload["load"]["chronic_load_range"] = {"min": 432.8, "max": 811.5}
        text = render(payload, None)
        self.assertIn("acute 491 / chronic 541", text)
        self.assertIn("chronic range 432.8–811.5", text)

    def test_load_balance_buckets_each_show_value_and_target(self):
        text = render(_payload(), None)
        self.assertIn("**Aerobic Low:** 516.6 (target 303–822 — in range)", text)
        self.assertIn("**Aerobic High:** 1541.9 (target 649–1169 — +373 over)", text)
        self.assertIn("**Anaerobic:** 67 (target 173–519 — -106 under)", text)
        self.assertIn("**Load focus:** Anaerobic Shortage", text)

    def test_running_tolerance_shows_raw_km_and_cap(self):
        payload = _payload()
        payload["running_tolerance"]["actual_7_day_distance"] = 34.2
        payload["running_tolerance"]["weekly_tolerance"] = 65.2
        payload["running_tolerance"]["acute_impact_load"] = 43.1
        text = render(payload, None)
        self.assertIn("34.2km of 65.2km weekly cap", text)
        self.assertIn("acute impact load 43.1", text)


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

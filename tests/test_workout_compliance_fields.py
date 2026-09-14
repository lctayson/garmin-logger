"""
Garmin's lap data includes wktStepIndex and directWorkoutComplianceScore
for laps executed as part of a structured workout loaded onto the watch
(built via Garmin Connect's workout builder). These weren't captured at
all previously:

- workout_step_index (raw wktStepIndex): which step of the structured
  workout this lap corresponds to.
- workout_compliance_pct (raw directWorkoutComplianceScore): a 0-100
  score of how well the actual execution matched that step's target
  (pace/power/HR range) -- useful for judging execution quality on
  prescribed interval/threshold sessions specifically.

Both are unitless integers, so they pass through activity_units.py's
_convert_split() untouched (no renaming/unit conversion needed) and only
need to be extracted in garmin_activity_enrichment.py and whitelisted in
split_garmin_json.py's SPLIT_COLUMN_ORDER (anything not listed there is
silently dropped from the final splits table).

Free (i.e. non-structured) laps -- warmup, cooldown, anything not run
from a loaded workout -- simply won't have these fields; they must not
misalign the positional splits table.
"""

import sys
import types

# garmin_activity_enrichment.py imports garmin_to_json, which imports the
# real garminconnect package -- stub it so these tests don't need it.
if "garminconnect" not in sys.modules:
    stub = types.ModuleType("garminconnect")
    stub.Garmin = type("Garmin", (), {})
    sys.modules["garminconnect"] = stub

from garmin_activity_enrichment import enrich_activity_splits
from split_garmin_json import _normalize_splits


class FakeApiWithWorkoutLap:
    """Returns one lap shaped exactly like a real structured-workout rep
    (per a raw capture from get_activity_splits)."""

    def get_activity_splits(self, activity_id):
        return {
            "lapDTOs": [
                {
                    "lapIndex": 7,
                    "wktStepIndex": 1,
                    "directWorkoutComplianceScore": 100,
                    "intensityType": "ACTIVE",
                    "duration": 20.0,
                    "distance": 60.26,
                    "averageSpeed": 3.013000011444092,
                    "avgGradeAdjustedSpeed": 2.7300000190734863,
                    "averageHR": 150.0,
                    "maxHR": 152.0,
                }
            ]
        }


class FakeApiFreeRun:
    """A lap with no structured-workout fields at all (a normal free run)."""

    def get_activity_splits(self, activity_id):
        return {
            "lapDTOs": [
                {
                    "lapIndex": 1,
                    "intensityType": "ACTIVE",
                    "duration": 300.0,
                    "distance": 1000.0,
                    "averageSpeed": 3.33,
                    "averageHR": 145.0,
                    "maxHR": 150.0,
                }
            ]
        }


def test_workout_step_index_and_compliance_extracted():
    activity = {"activityId": 123, "activity_splits": [{"lap": 7}]}
    enrich_activity_splits(FakeApiWithWorkoutLap(), activity)
    item = activity["activity_splits"][0]
    assert item["workout_step_index"] == 1
    assert item["workout_compliance_pct"] == 100


def test_free_run_lap_has_no_workout_fields():
    """A lap with no wktStepIndex/directWorkoutComplianceScore in the raw
    response must simply omit these keys, not error or set them to None."""
    activity = {"activityId": 456, "activity_splits": [{"lap": 1}]}
    enrich_activity_splits(FakeApiFreeRun(), activity)
    item = activity["activity_splits"][0]
    assert "workout_step_index" not in item
    assert "workout_compliance_pct" not in item


def test_mixed_laps_stay_positionally_aligned_in_final_table():
    """A day with a warmup lap (no workout fields) followed by structured
    reps (with them) must not misalign the splits columns/data table --
    missing fields become null in that lap's row, not a shifted row."""
    activity = {
        "activity_splits": [
            {"lap": 1, "step_type": "ACTIVE", "avg_hr": 138.0},
            {"lap": 7, "step_type": "ACTIVE", "workout_step_index": 1, "workout_compliance_pct": 100, "avg_hr": 150.0},
            {"lap": 8, "step_type": "RECOVERY", "workout_step_index": 2, "workout_compliance_pct": 87, "avg_hr": 142.0},
        ]
    }
    result = _normalize_splits(activity)
    idx = result["columns"].index("workout_step_index")
    pct_idx = result["columns"].index("workout_compliance_pct")
    lap_idx = result["columns"].index("lap")

    rows_by_lap = {row[lap_idx]: row for row in result["data"]}
    assert rows_by_lap[1][idx] is None and rows_by_lap[1][pct_idx] is None
    assert rows_by_lap[7][idx] == 1 and rows_by_lap[7][pct_idx] == 100
    assert rows_by_lap[8][idx] == 2 and rows_by_lap[8][pct_idx] == 87

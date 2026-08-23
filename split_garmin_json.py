"""Split and compact the generated Garmin snapshot.

Outputs for target date YYYY-MM-DD:
  data/YYYY/MM/YYYY-MM-DD_daily.json
  data/YYYY/MM/YYYY-MM-DD_activities.json
  data/YYYY/MM/YYYY-MM-DD_trends.json
  data/latest_daily.json
  data/latest_activities.json
  data/latest_trends.json

Field names are intentionally shortened but remain human-readable. Historical
trend series are kept separate so the daily and activity files stay small.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime


ACTIVITY_KEYS = ("activities", "activity_data", "activityData")
TREND_KEYS = (
    "training_history",
    "trend_recent_daily",
    "trend_long_range_weekly",
    "body_battery_trend",
)

# Long Garmin/export names -> concise, still-readable names.
KEY_MAP = {
    # General / daily
    "resting_heart_rate": "resting_hr",
    "total_steps": "steps",
    "total_sleep_hours": "sleep_h",
    "sleep_stages_hours": "sleep_stages_h",
    "training_history": "training_history",
    "7_day_distance_km": "7d_dist_km",
    "28_day_avg_weekly_distance_km": "28d_avg_weekly_km",
    "weekly_distance_last_4_weeks_km": "weekly_km_4w",
    "last_night_avg_ms": "last_night_avg_ms",
    "seven_day_avg_ms": "7d_avg_ms",
    "baseline_balanced_range": "baseline_balanced",
    "balanced_low": "balanced_low",
    "balanced_upper": "balanced_upper",
    "low_upper": "low_upper",
    "marker_value": "marker",
    "sleep_score": "sleep_score",
    "health_stats": "health_stats",
    "training_status": "training_status",
    "acute_training_load": "acute_load",
    "recovery_time_hours": "recovery_h",
    "load_focus": "load_focus",
    "vo2_max": "vo2_max",
    "heat_acclimation": "heat_acclim",
    "altitude_acclimation": "altitude_acclim",
    "percentage": "pct",
    "trend": "trend",
    "value": "value",
    "status": "status",

    # Activity summary
    "activityId": "id",
    "distance_km": "dist_km",
    "duration_mins": "duration_min",
    "average_hr": "avg_hr",
    "max_hr": "max_hr",
    "aerobic_training_effect": "aerobic_te",
    "anaerobic_training_effect": "anaerobic_te",
    "exercise_load": "load",
    "activity_splits": "splits",
    "parentActivityId": "parent_id",

    # Activity lap/split fields
    "time_min": "time_min",
    "cumulative_time_min": "cum_time_min",
    "moving_time_min": "moving_time_min",
    "avg_moving_pace": "avg_moving_pace",
    "best_pace": "best_pace",
    "calories": "cal",
    "avg_power_w": "avg_power_w",
    "normalized_power_w": "norm_power_w",
    "cadence_spm": "cadence_spm",
    "max_cadence_spm": "max_cadence_spm",
    "avg_gct_ms": "gct_ms",
    "avg_stride_length_m": "stride_m",
    "vertical_oscillation_cm": "vertical_cm",
    "vertical_ratio_pct": "vertical_ratio_pct",
    "elevation_gain_m": "elev_gain_m",
    "elevation_loss_m": "elev_loss_m",
    "intensityType": "intensity",
}


def compact_keys(obj):
    """Recursively shorten known keys while leaving values and unknown keys intact."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            new_key = KEY_MAP.get(key, key)
            if new_key in out and new_key != key:
                raise ValueError(f"Key collision while compacting: {key} -> {new_key}")
            out[new_key] = compact_keys(value)
        return out
    if isinstance(obj, list):
        return [compact_keys(item) for item in obj]
    return obj


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def split_payload(payload: dict) -> tuple[dict, dict, dict]:
    activity_key = next((key for key in ACTIVITY_KEYS if key in payload), None)
    if activity_key is None:
        raise KeyError(
            "Could not find the activity section. Expected one of: "
            + ", ".join(ACTIVITY_KEYS)
        )

    trend_keys_present = [key for key in TREND_KEYS if key in payload]
    daily = {
        key: value
        for key, value in payload.items()
        if key != activity_key and key not in trend_keys_present
    }
    activities = {
        "date": payload.get("date"),
        activity_key: payload.get(activity_key),
    }
    trends = {
        "date": payload.get("date"),
        **{key: payload[key] for key in trend_keys_present},
    }
    return compact_keys(daily), compact_keys(activities), compact_keys(trends)


def write_json(path: str, payload: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    latest_path = os.path.join(args.data_dir, "latest.json")
    if not os.path.isfile(latest_path):
        raise FileNotFoundError(f"Missing generated file: {latest_path}")

    payload = load_json(latest_path)
    target_date = args.date or payload.get("date")
    if not target_date:
        raise ValueError("Target date is missing from --date and generated JSON")
    target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    payload_date = payload.get("date")
    if payload_date and payload_date != target_date.isoformat():
        raise ValueError(
            f"Date mismatch: --date={target_date.isoformat()} but JSON date={payload_date}"
        )

    daily, activities, trends = split_payload(payload)

    month_dir = os.path.join(
        args.data_dir,
        f"{target_date.year:04d}",
        f"{target_date.month:02d}",
    )
    os.makedirs(month_dir, exist_ok=True)

    dated_daily = os.path.join(month_dir, f"{target_date.isoformat()}_daily.json")
    dated_activities = os.path.join(month_dir, f"{target_date.isoformat()}_activities.json")
    dated_trends = os.path.join(month_dir, f"{target_date.isoformat()}_trends.json")
    latest_daily = os.path.join(args.data_dir, "latest_daily.json")
    latest_activities = os.path.join(args.data_dir, "latest_activities.json")
    latest_trends = os.path.join(args.data_dir, "latest_trends.json")

    write_json(dated_daily, daily)
    write_json(dated_activities, activities)
    write_json(dated_trends, trends)

    shutil.copyfile(dated_daily, latest_daily)
    shutil.copyfile(dated_activities, latest_activities)
    shutil.copyfile(dated_trends, latest_trends)

    old_dated = os.path.join(month_dir, f"{target_date.isoformat()}.json")
    if os.path.exists(old_dated):
        os.remove(old_dated)
    os.remove(latest_path)

    print(f"Created {dated_daily}")
    print(f"Created {dated_activities}")
    print(f"Created {dated_trends}")
    print(f"Updated {latest_daily}")
    print(f"Updated {latest_activities}")
    print(f"Updated {latest_trends}")


if __name__ == "__main__":
    main()

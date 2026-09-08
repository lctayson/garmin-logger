#!/usr/bin/env python3
"""
Split the consolidated Garmin JSON into the dated metrics and activities files.
"""

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Manila")

ACTIVITY_KEY_ORDER = (
    "name", "activity_id", "type",
    "distance", "time", "elapsed_time", "moving_time", "avg_pace", "gap",
    "avg_hr", "max_hr", "recovery_hr",
    "elevation_gain", "elevation_loss", "calories", "load", "start_time_local",
    "activity_vo2max", "training_effect", "exercise_load", "recovery_time_hours",
    "avg_power", "normalized_power", "max_power",
    "avg_run_cadence", "max_run_cadence", "avg_ground_contact_time", "stride_length",
    "avg_vertical_oscillation", "avg_vertical_ratio", "avg_power_to_weight", "max_power_to_weight",
    "interval_drift", "decoupling", "splits",
    "weather", "hr_zones", "power_zones", "lap_count",
    "parent_activity_id",
)

TRAINING_EFFECT_KEY_ORDER = ("label", "aerobic", "aerobic_message", "anaerobic", "anaerobic_message")
INTERVAL_DRIFT_KEY_ORDER = ("work_reps", "pace_ef_drift_pct", "hr_delta_bpm", "power_ef_drift_pct", "power_delta_w")
WEATHER_KEY_ORDER = ("temperature", "humidity_pct", "wind_speed", "wind_direction_deg")
ZONE_KEY_ORDER = ("columns", "data")
DEFAULT_UNITS = {"distance": "km", "pace": "min/km", "elevation": "m", "stride_length": "m", "vertical_oscillation": "cm", "temperature": "°C", "wind_speed": "m/s", "precipitation": "mm"}

SPLIT_COLUMN_ORDER = (
    "step_type", "lap", "time", "avg_pace", "avg_gap", "avg_hr", "max_hr", "start_hr", "min_hr",
    "end_hr", "avg_run_cadence", "calories", "best_pace", "max_run_cadence", "moving_time",
    "avg_moving_pace", "distance", "elevation_gain", "elevation_loss", "stride_length",
    "avg_vertical_oscillation", "avg_ground_contact_time", "normalized_power", "avg_power",
    "max_power", "avg_vertical_ratio",
)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def write_json(path, payload, activity_compact=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if activity_compact:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def split_payload(payload):
    metrics = {k: v for k, v in payload.items() if k != "activities"}
    activities = payload.get("activities", [])
    return metrics, activities


def _ordered_dict(source, key_order):
    if not isinstance(source, dict):
        return source
    return {key: source[key] for key in key_order if key in source and source[key] is not None}


def _normalize_splits(activity):
    splits = activity.get("splits")
    if isinstance(splits, dict) and isinstance(splits.get("columns"), list) and isinstance(splits.get("data"), list):
        source_columns = splits["columns"]
        rows = []
        for row in splits["data"]:
            if not isinstance(row, list):
                continue
            values = dict(zip(source_columns, row))
            rows.append([values.get(column) for column in SPLIT_COLUMN_ORDER])
        return {"columns": list(SPLIT_COLUMN_ORDER), "data": rows}

    raw_splits = activity.get("activity_splits")
    if not isinstance(raw_splits, list):
        return None
    return {
        "columns": list(SPLIT_COLUMN_ORDER),
        "data": [[split.get(column) for column in SPLIT_COLUMN_ORDER] for split in raw_splits if isinstance(split, dict)],
    }


def _normalize_nested(activity):
    for key, order in (("training_effect", TRAINING_EFFECT_KEY_ORDER), ("interval_drift", INTERVAL_DRIFT_KEY_ORDER), ("weather", WEATHER_KEY_ORDER)):
        if isinstance(activity.get(key), dict):
            activity[key] = _ordered_dict(activity[key], order)
    for key in ("hr_zones", "power_zones"):
        if isinstance(activity.get(key), dict):
            activity[key] = _ordered_dict(activity[key], ZONE_KEY_ORDER)


def normalize_activity(activity):
    """Normalize one activity to the ActivityReport schema's field order."""
    if not isinstance(activity, dict):
        return activity
    out = dict(activity)
    if "activity_id" not in out and out.get("activityId") is not None:
        out["activity_id"] = out["activityId"]
    if "avg_hr" not in out and out.get("average_hr") is not None:
        out["avg_hr"] = out["average_hr"]
    if "load" not in out and out.get("exercise_load") is not None:
        out["load"] = out["exercise_load"]
    out.pop("activityId", None)
    out.pop("average_hr", None)
    out.pop("exercise_load", None)
    for key in ("duration_min", "aerobic_te", "anaerobic_te", "training_effect_label"):
        out.pop(key, None)
    normalized_splits = _normalize_splits(out)
    out.pop("activity_splits", None)
    if normalized_splits is not None:
        out["splits"] = normalized_splits
    _normalize_nested(out)
    return {key: out[key] for key in ACTIVITY_KEY_ORDER if key in out and out[key] is not None}


def normalize_activities(activities):
    return [normalize_activity(activity) for activity in (activities or [])]


def _normalize_root_units(units):
    source = units if isinstance(units, dict) else {}
    return {key: source.get(key, default) for key, default in DEFAULT_UNITS.items()}


def refresh_latest_activities(data_dir, target_date, current_path, has_activity, today):
    if not has_activity or target_date != today:
        return False
    latest_path = os.path.join(data_dir, "latest_activities.json")
    with open(current_path, "r", encoding="utf-8") as src:
        payload = json.load(src)
    write_json(latest_path, payload, activity_compact=False)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--input", default=None)
    args = parser.parse_args()
    today = datetime.now(LOCAL_TZ).date()
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else today
    input_path = args.input or os.path.join(args.data_dir, "latest.json")
    payload = load_json(input_path)
    metrics, activities = split_payload(payload)
    activities = normalize_activities(activities)
    dated_metrics = os.path.join(args.data_dir, f"metrics_{target_date:%Y-%m-%d}.json")
    dated_activities = os.path.join(args.data_dir, f"activities_{target_date:%Y-%m-%d}.json")
    write_json(dated_metrics, metrics)
    root_units = _normalize_root_units(payload.get("units", {}))
    write_json(dated_activities, {"date": target_date.isoformat(), "units": root_units, "activities": activities}, activity_compact=False)
    refresh_latest_activities(args.data_dir, target_date, dated_activities, bool(activities), today)


if __name__ == "__main__":
    main()

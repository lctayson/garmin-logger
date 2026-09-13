#!/usr/bin/env python3
"""
Split the consolidated Garmin JSON into the dated metrics and activities files.
"""

import argparse
import json
import os
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from compact_metrics import compact_metrics
from metrics_units import apply_metrics_units

LOCAL_TZ = ZoneInfo("Asia/Manila")

ACTIVITY_KEY_ORDER = (
    "name", "activity_id", "type",
    "distance", "time", "elapsed_time", "moving_time", "avg_pace", "gap",
    "avg_hr", "max_hr", "recovery_hr",
    "elevation_gain", "elevation_loss", "calories", "load", "start_time_local",
    "activity_vo2max", "performance_condition_start", "performance_condition_end", "performance_condition_avg",
    "training_effect", "exercise_load", "recovery_time_hours",
    "begin_stamina_pct", "end_stamina_pct", "min_stamina_pct", "stamina_used_pct", "impact_load",
    "avg_power", "normalized_power", "max_power",
    "avg_run_cadence", "max_run_cadence", "avg_ground_contact_time", "stride_length",
    "avg_vertical_oscillation", "avg_vertical_ratio", "avg_power_to_weight", "max_power_to_weight",
    "interval_drift", "decoupling", "splits",
    "weather", "hr_zones", "power_zones", "lap_count",
    "parent_activity_id",
)

TRAINING_EFFECT_KEY_ORDER = ("label", "aerobic", "aerobic_message", "anaerobic", "anaerobic_message")
INTERVAL_DRIFT_KEY_ORDER = ("work_reps", "pace_ef_drift_pct", "hr_delta_bpm", "power_ef_drift_pct", "power_delta_w")
WEATHER_KEY_ORDER = ("temperature", "feels_like", "dew_point", "humidity_pct", "wind_speed", "wind_direction_deg", "condition")
ZONE_KEY_ORDER = ("columns", "data")
DEFAULT_UNITS = {"distance": "km", "pace": "min/km", "elevation": "m", "stride_length": "m", "vertical_oscillation": "cm", "temperature": "°C", "wind_speed": "m/s", "precipitation": "mm"}

SPLIT_COLUMN_ORDER = (
    "step_type", "lap", "time", "elapsed_time", "avg_pace", "avg_gap", "avg_hr", "max_hr", "start_hr", "min_hr",
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


def _dump_pretty(value, level=0, table=False):
    """Pretty-print JSON while keeping table columns and rows on single lines."""
    indent = "  " * level
    child_indent = "  " * (level + 1)

    if isinstance(value, dict):
        if not value:
            return "{}"
        parts = []
        for key, val in value.items():
            key_json = json.dumps(key, ensure_ascii=False)
            if key in ("columns", "data") and isinstance(val, list):
                if key == "columns":
                    val_json = json.dumps(val, ensure_ascii=False, separators=(", ", ": "))
                else:
                    rows = []
                    for row in val:
                        rows.append(child_indent + json.dumps(row, ensure_ascii=False, separators=(", ", ": ")))
                    val_json = "[\n" + ",\n".join(rows) + "\n" + indent + "]"
            else:
                val_json = _dump_pretty(val, level + 1)
            parts.append(f"{child_indent}{key_json}: {val_json}")
        return "{\n" + ",\n".join(parts) + "\n" + indent + "}"

    if isinstance(value, list):
        if not value:
            return "[]"
        parts = [_dump_pretty(item, level + 1) for item in value]
        return "[\n" + ",\n".join(child_indent + item for item in parts) + "\n" + indent + "]"

    return json.dumps(value, ensure_ascii=False)


def write_json(path, payload, activity_compact=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if activity_compact:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            fh.write(_dump_pretty(payload))
        fh.write("\n")


def split_payload(payload):
    metrics = {k: v for k, v in payload.items() if k != "activities"}
    activities = payload.get("activities", [])
    return metrics, activities


def _ordered_dict(source, key_order):
    if not isinstance(source, dict):
        return source
    return {key: source[key] for key in key_order if key in source and source[key] is not None}


def _duration(seconds):
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return None
    return f"{total // 60}:{total % 60:02d}" if total >= 0 else None


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
    rows = []
    for split in raw_splits:
        if not isinstance(split, dict):
            continue
        row = []
        for column in SPLIT_COLUMN_ORDER:
            value = split.get(column)
            if column == "elapsed_time" and value is None:
                value = _duration(split.get("elapsedDuration"))
            row.append(value)
        rows.append(row)
    return {"columns": list(SPLIT_COLUMN_ORDER), "data": rows}


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
    if "parent_activity_id" not in out and out.get("parentActivityId") is not None:
        out["parent_activity_id"] = out["parentActivityId"]
    if "avg_hr" not in out and out.get("average_hr") is not None:
        out["avg_hr"] = out["average_hr"]
    if "load" not in out and out.get("exercise_load") is not None:
        out["load"] = out["exercise_load"]
    out.pop("activityId", None)
    out.pop("parentActivityId", None)
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


def slugify(name):
    """Turn an activity name into a filename-safe slug, e.g. 'Bohol 5150' -> 'bohol-5150'."""
    if not name:
        return None
    normalized = unicodedata.normalize("NFKD", name)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_str).strip("-").lower()
    return slug or None


def _common_leading_text(names):
    """Return the longest common leading substring of a list of names, with
    trailing separators trimmed, e.g. ['Bohol 5150 - Swim', 'Bohol 5150 - Bike']
    -> 'Bohol 5150'. Returns None if there's nothing meaningful in common."""
    names = [n for n in names if n]
    if not names:
        return None
    prefix = names[0]
    for other in names[1:]:
        limit = min(len(prefix), len(other))
        i = 0
        while i < limit and prefix[i] == other[i]:
            i += 1
        prefix = prefix[:i]
        if not prefix:
            break
    prefix = prefix.rstrip(" \t-\u2013\u2014:|/").strip()
    return prefix or None


def _duration_seconds(value):
    """Parse a 'H:MM:SS' or 'MM:SS' duration string into seconds for comparison."""
    if not value:
        return 0
    parts = str(value).split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def primary_activity_slug(activities):
    """Pick the longest-duration activity of the day and slugify its name.

    On multi-activity days (e.g. a short walk plus the main workout), this
    picks the one with the longest moving/elapsed time so filenames reflect
    the day's main activity rather than an incidental one.

    Multisport events (triathlons, duathlons) are expanded upstream into
    individual legs that share a common parent_activity_id, and each leg
    keeps its own name (e.g. "Bohol 5150 - Cycling") with no leg holding the
    overall event name. Comparing legs individually would pick whichever leg
    happens to be longest (usually the bike) and name the file after that
    leg alone. Instead, legs sharing a parent_activity_id are grouped and
    compared as one activity using their combined duration, and the event
    name is recovered from the common prefix shared by the (non-transition)
    leg names.
    """
    candidates = [a for a in (activities or []) if isinstance(a, dict) and a.get("name")]
    if not candidates:
        return None

    def leg_duration(a):
        return max(
            _duration_seconds(a.get("moving_time")),
            _duration_seconds(a.get("time")),
            _duration_seconds(a.get("elapsed_time")),
        )

    def is_transition(a):
        return "transition" in (a.get("type") or "").lower() or str(a.get("name", "")).lower().startswith("transition")

    groups = {}
    contenders = []
    for a in candidates:
        parent = a.get("parent_activity_id")
        if parent:
            groups.setdefault(parent, []).append(a)
        else:
            contenders.append({"name": a.get("name"), "duration": leg_duration(a)})

    for legs in groups.values():
        real_legs = [leg for leg in legs if not is_transition(leg)]
        names = [leg.get("name") for leg in real_legs] or [leg.get("name") for leg in legs]
        event_name = _common_leading_text(names) or (names[0] if names else None)
        contenders.append({"name": event_name, "duration": sum(leg_duration(leg) for leg in legs)})

    if not contenders:
        return None
    longest = max(contenders, key=lambda c: c["duration"])
    return slugify(longest.get("name"))


def refresh_latest_metrics(data_dir, target_date, current_path, today):
    if target_date != today:
        return False
    latest_path = os.path.join(data_dir, "latest_metrics.json")
    with open(current_path, "r", encoding="utf-8") as src:
        payload = json.load(src)
    write_json(latest_path, payload, activity_compact=False)
    return True


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
    metrics = compact_metrics(metrics)
    metrics = apply_metrics_units(metrics, payload.get("_measurement_system"))
    dated_dir = os.path.join(args.data_dir, f"{target_date:%Y}", f"{target_date:%m}")
    dated_metrics = os.path.join(dated_dir, f"{target_date:%Y-%m-%d}_metrics.json")
    write_json(dated_metrics, metrics)
    refresh_latest_metrics(args.data_dir, target_date, dated_metrics, today)
    slug = primary_activity_slug(activities)
    if slug:
        dated_activities = os.path.join(dated_dir, f"{target_date:%Y-%m-%d}_{slug}.json")
        root_units = _normalize_root_units(payload.get("units", {}))
        write_json(dated_activities, {"date": target_date.isoformat(), "units": root_units, "activities": activities}, activity_compact=False)
        refresh_latest_activities(args.data_dir, target_date, dated_activities, True, today)


if __name__ == "__main__": main()
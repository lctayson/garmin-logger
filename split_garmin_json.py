"""Split the generated Garmin snapshot into canonical metrics and activity JSON."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

from compact_metrics import compact_metrics
from metrics_units import apply_metrics_units

ACTIVITY_KEYS = ("activities", "activity_data", "activityData")
LOCAL_TZ = ZoneInfo("Asia/Manila")

KEY_MAP = {
    "resting_heart_rate": "resting_hr", "resting_hr_bpm": "resting_hr", "total_steps": "steps",
    "total_sleep_hours": "sleep_hours", "7_day_distance_km": "7d_distance_km",
    "28_day_avg_weekly_distance_km": "28d_avg_weekly_distance_km", "weekly_distance_last_4_weeks_km": "weekly_distance_4w_km",
    "last_night_avg_ms": "last_night_avg_ms", "seven_day_avg_ms": "7d_avg_ms", "acute_training_load": "acute_load",
    "recovery_time_hours": "recovery_hours", "activityId": "activity_id", "duration_mins": "duration_min",
    "average_heart_rate": "avg_hr", "average_hr": "avg_hr", "aerobic_training_effect": "aerobic_te",
    "anaerobic_training_effect": "anaerobic_te", "exercise_load": "load", "activity_splits": "splits",
    "parentActivityId": "parent_activity_id", "avg_gct_ms": "ground_contact_ms", "avg_stride_length_m": "stride_length_m",
    "intensityType": "intensity",
}


def compact_keys(obj):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            new_key = KEY_MAP.get(key, key)
            if new_key in out and new_key != key:
                continue
            out[new_key] = compact_keys(value)
        return out
    if isinstance(obj, list):
        return [compact_keys(item) for item in obj]
    return obj


def to_columnar(rows):
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
        return rows
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return {"columns": columns, "data": [[row.get(column) for column in columns] for row in rows]}


def _pace_to_speed_kmh(pace):
    if not isinstance(pace, str) or ":" not in pace:
        return None
    try:
        minutes, seconds = pace.split(":", 1)
        pace_seconds = float(minutes) * 60.0 + float(seconds)
    except (TypeError, ValueError):
        return None
    return 3600.0 / pace_seconds if pace_seconds > 0 else None


def _split_duration_seconds(row):
    value = row.get("time")
    if isinstance(value, str) and ":" in value:
        try:
            parts = [float(part) for part in value.split(":")]
            if len(parts) == 2:
                return parts[0] * 60.0 + parts[1]
            if len(parts) == 3:
                return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
        except (TypeError, ValueError):
            pass
    return None


def _calculate_interval_drift(activity):
    """Add normalized first-to-last work-rep efficiency drift.

    This is deliberately separate from continuous-run ``decoupling``. It uses
    ACTIVE work reps of at least 90 seconds, which excludes short strides and
    transition laps while covering the user's 3-12 minute interval work.
    Pace EF is speed/HR; power EF uses average power/HR, never normalized power.
    """
    if not isinstance(activity, dict) or str(activity.get("type", "")).lower() != "running":
        return

    splits = activity.get("splits")
    if not isinstance(splits, list):
        return

    rows = [row for row in splits if isinstance(row, dict)]
    if not rows:
        return

    active_rows = []
    for row in rows:
        if str(row.get("step_type", "")).upper() != "ACTIVE":
            continue
        duration = _split_duration_seconds(row)
        if duration is None or duration < 90.0:
            continue
        active_rows.append(row)

    if len(active_rows) < 2:
        return

    reps = []
    for row in active_rows:
        hr = row.get("avg_hr")
        speed = _pace_to_speed_kmh(row.get("avg_pace"))
        if speed is None:
            continue
        try:
            hr = float(hr)
        except (TypeError, ValueError):
            continue
        if hr <= 0:
            continue

        rep = {
            "hr": hr,
            "speed_kmh": speed,
            "ef": speed / hr,
            "lap": row.get("lap"),
        }
        power = row.get("avg_power")
        try:
            power = float(power) if power is not None else None
        except (TypeError, ValueError):
            power = None
        if power is not None and power > 0:
            rep["power"] = power
            rep["ef_power"] = power / hr
        reps.append(rep)

    if len(reps) < 2:
        return

    first = reps[0]
    last = reps[-1]
    first_ef = first["ef"]
    if first_ef <= 0:
        return

    result = {
        "work_reps": len(reps),
        "pace_ef_drift_pct": round((first_ef - last["ef"]) / first_ef * 100.0, 1),
        "hr_delta_bpm": round(last["hr"] - first["hr"], 1),
    }

    if "ef_power" in first and "ef_power" in last and first["ef_power"] > 0:
        result["power_ef_drift_pct"] = round(
            (first["ef_power"] - last["ef_power"]) / first["ef_power"] * 100.0,
            1,
        )
        result["power_delta_w"] = round(last["power"] - first["power"], 1)

    activity["interval_drift"] = result


def _reorder_activity(activity):
    """Put compact activity fields in stable Garmin Connect-style priority order."""
    priority = (
        "name", "activity_id", "type",
        "distance", "duration_min", "avg_pace", "gap",
        "avg_hr", "max_hr", "recovery_hr",
        "elevation_gain", "elevation_loss", "calories",
        "avg_power", "normalized_power", "max_power",
        "avg_run_cadence", "max_run_cadence", "avg_ground_contact_time", "stride_length",
        "avg_vertical_oscillation", "avg_vertical_ratio", "avg_power_to_weight", "max_power_to_weight",
        "interval_drift",
        "aerobic_te", "anaerobic_te", "load", "exercise_load", "recovery_time_hours",
        "start_time_local", "weather",
        "hr_zones", "power_zones", "splits",
        "parent_activity_id", "units",
    )
    ordered = {}
    for key in priority:
        if key in activity and activity[key] is not None:
            ordered[key] = activity[key]
    for key, value in activity.items():
        if key not in ordered and value is not None:
            ordered[key] = value
    return ordered


def compact_activity(activity):
    activity = compact_keys(activity)
    _calculate_interval_drift(activity)
    split_key = next((key for key in ("splits", "laps") if key in activity), None)
    if split_key:
        splits = activity[split_key]
        if isinstance(splits, list):
            splits = [{key: value for key, value in row.items() if key != "time_seconds"} if isinstance(row, dict) else row for row in splits]
        activity[split_key] = to_columnar(splits)
    return _reorder_activity(activity)


def compact_activities(value):
    if not isinstance(value, list):
        return value
    return [compact_activity(activity) if isinstance(activity, dict) else activity for activity in value]


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def split_payload(payload):
    """Build both outputs without writing an intermediate metrics representation."""
    activity_key = next((key for key in ACTIVITY_KEYS if key in payload), None)
    if activity_key is None:
        raise KeyError("Could not find the activity section")

    metrics = compact_metrics(payload)
    measurement_system = payload.get("_measurement_system", "metric")
    metrics = apply_metrics_units(metrics, measurement_system)
    activities = {
        "date": payload.get("date"),
        "activities": compact_activities(payload.get(activity_key)),
    }
    return metrics, activities


def _compact_array_property(text, property_name):
    marker = f'"{property_name}": ['
    search_from = 0
    while True:
        marker_pos = text.find(marker, search_from)
        if marker_pos < 0:
            break
        array_start = marker_pos + len(f'"{property_name}": ')
        depth = 0
        in_string = False
        escaped = False
        array_end = None
        for i in range(array_start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    array_end = i
                    break
        if array_end is None:
            break
        values = json.loads(text[array_start:array_end + 1])
        compact = json.dumps(values, ensure_ascii=False, separators=(", ", ": "))
        text = text[:array_start] + compact + text[array_end + 1:]
        search_from = array_start + len(compact)
    return text


def _compact_data_arrays(text):
    text = _compact_array_property(text, "columns")
    marker = '"data": ['
    search_from = 0
    while True:
        marker_pos = text.find(marker, search_from)
        if marker_pos < 0:
            break
        array_start = marker_pos + len('"data": ')
        depth = 0
        in_string = False
        escaped = False
        array_end = None
        for i in range(array_start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    array_end = i
                    break
        if array_end is None:
            break
        rows = json.loads(text[array_start:array_end + 1])
        indent = len(text[:marker_pos].rsplit("\n", 1)[-1])
        row_indent = " " * (indent + 2)
        row_text = "[\n" + ",\n".join(row_indent + json.dumps(row, ensure_ascii=False, separators=(", ", ": ")) for row in rows) + "\n" + " " * indent + "]"
        text = text[:array_start] + row_text + text[array_end + 1:]
        search_from = array_start + len(row_text)
    return text


def _render_metrics_json(payload):
    items = list(payload.items())
    lines = ["{"]
    compact_tail = False
    for index, (key, value) in enumerate(items):
        if key == "training_history":
            compact_tail = True
        if compact_tail:
            rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            line = "  " + json.dumps(key, ensure_ascii=False) + ": " + rendered
        else:
            block = json.dumps({key: value}, ensure_ascii=False, indent=2).splitlines()
            line = "\n".join(block[1:-1])
        if index < len(items) - 1:
            line += ","
        lines.append(line)
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_json(path, payload, activity_compact=False):
    tmp = f"{path}.tmp"
    if activity_compact:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        text = _compact_data_arrays(text)
    else:
        text = _render_metrics_json(payload)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def refresh_latest_activities(data_dir, target_date, dated_activities, has_activities, today_date=None):
    if today_date is None:
        today_date = datetime.now(LOCAL_TZ).date()
    if target_date != today_date or not has_activities or not os.path.isfile(dated_activities):
        return False
    latest_path = os.path.join(data_dir, "latest_activities.json")
    shutil.copyfile(dated_activities, latest_path)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    latest_path = os.path.join(args.data_dir, "latest.json")
    if not os.path.isfile(latest_path):
        raise FileNotFoundError(f"Missing generated file: {latest_path}")
    payload = load_json(latest_path)
    target_date = args.date or payload.get("date")
    if not target_date:
        raise ValueError("Target date is missing")
    target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    if payload.get("date") and payload["date"] != target_date.isoformat():
        raise ValueError(f"Date mismatch: --date={target_date.isoformat()} but JSON date={payload['date']}")
    metrics, activities = split_payload(payload)
    has_activities = isinstance(activities.get("activities"), list) and len(activities["activities"]) > 0
    month_dir = os.path.join(args.data_dir, f"{target_date.year:04d}", f"{target_date.month:02d}")
    os.makedirs(month_dir, exist_ok=True)
    dated_metrics = os.path.join(month_dir, f"{target_date.isoformat()}_metrics.json")
    dated_activities = os.path.join(month_dir, f"{target_date.isoformat()}_activities.json")
    write_json(dated_metrics, metrics)
    today_local = datetime.now(LOCAL_TZ).date()
    if target_date == today_local:
        shutil.copyfile(dated_metrics, os.path.join(args.data_dir, "latest_metrics.json"))
    if has_activities:
        write_json(dated_activities, activities, activity_compact=True)
    elif os.path.exists(dated_activities):
        os.remove(dated_activities)
    refresh_latest_activities(args.data_dir, target_date, dated_activities, has_activities, today_local)
    for old_name in ("latest_daily.json", "latest_trends.json"):
        old_path = os.path.join(args.data_dir, old_name)
        if os.path.exists(old_path):
            os.remove(old_path)
    for old_suffix in ("_daily.json", "_trends.json"):
        old_path = os.path.join(month_dir, f"{target_date.isoformat()}{old_suffix}")
        if os.path.exists(old_path):
            os.remove(old_path)
    old_dated = os.path.join(month_dir, f"{target_date.isoformat()}.json")
    if os.path.exists(old_dated):
        os.remove(old_dated)
    os.remove(latest_path)


if __name__ == "__main__":
    main()

import os
import json
import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from garminconnect import Garmin

def safe_float(val, decimals=2):
    if val is None or val == "N/A" or val == "":
        return None
    try:
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return None

def safe_int(val):
    if val is None or val == "N/A" or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None

def format_time(seconds):
    if not seconds or seconds <= 0:
        return None
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"

def speed_to_pace_metrics(speed_mps):
    if not speed_mps or speed_mps <= 0:
        return None, None
    sec_per_km = 1000.0 / float(speed_mps)
    formatted_pace = format_time(sec_per_km)
    decimal_pace = round(sec_per_km, 1)
    return formatted_pace, decimal_pace

def swim_speed_to_pace_metrics(speed_mps):
    if not speed_mps or speed_mps <= 0:
        return None, None
    # Swim pace is conventionally tracked per 100 meters/yards
    sec_per_100m = 100.0 / float(speed_mps)
    formatted_pace = format_time(sec_per_100m)
    decimal_pace = round(sec_per_100m, 1)
    return formatted_pace, decimal_pace


def speed_to_kph(speed_mps):
    """Convert Garmin m/s to km/h."""
    if speed_mps is None:
        return None
    try:
        speed_mps = float(speed_mps)
        if speed_mps < 0:
            return None
        return round(speed_mps * 3.6, 2)
    except (ValueError, TypeError):
        return None


def normalize_discipline(value):
    """Map Garmin activity/sport strings to stable analysis-friendly names."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = deep_get(value, ["typeKey", "key", "name"], None)
    if value is None:
        return None

    s = str(value).strip().lower().replace("-", "_").replace(" ", "_")

    if "swim" in s:
        return "swim"
    if any(x in s for x in ["cycling", "biking", "bike", "cycle"]):
        return "bike"
    if "run" in s:
        return "run"
    if "walk" in s:
        return "walk"
    if any(x in s for x in ["transition", "trans"]):
        return "transition"
    if any(x in s for x in ["strength", "weight"]):
        return "strength"
    if any(x in s for x in ["multi_sport", "multisport", "triathlon"]):
        return "multi_sport"

    return s or None


def lap_discipline_from_api(lap):
    """Read per-lap discipline from Garmin when it is available."""
    raw = deep_get(
        lap,
        [
            "activityType.typeKey",
            "activityTypeDTO.typeKey",
            "sportType.typeKey",
            "sportType",
            "subSportType.typeKey",
            "subSportType",
            "typeKey",
            "activityType",
        ],
        None,
    )
    return normalize_discipline(raw)


def infer_triathlon_segment_types(lap_dtos):
    """
    Conservative fallback for a standard five-part triathlon:
    swim, T1, bike, T2, run.

    No label is invented unless the lap geometry strongly matches that pattern.
    """
    labels = [None] * len(lap_dtos)
    if len(lap_dtos) != 5:
        return labels

    def dist_km(lap):
        value = safe_float(lap.get("distance"), 3)
        return value / 1000.0 if value is not None else None

    d = [dist_km(lap) for lap in lap_dtos]
    speeds = [safe_float(lap.get("averageSpeed"), 3) for lap in lap_dtos]
    durations_min = [
        safe_float((lap.get("duration") or 0) / 60.0, 2)
        if lap.get("duration") is not None else None
        for lap in lap_dtos
    ]

    checks = [
        d[0] is not None and 0.2 <= d[0] <= 5.0
        and speeds[0] is not None and speeds[0] < 2.5,

        d[1] is not None and d[1] <= 2.0
        and durations_min[1] is not None and durations_min[1] <= 20,

        d[2] is not None and d[2] >= 5.0
        and speeds[2] is not None and speeds[2] >= 4.0,

        d[3] is not None and d[3] <= 2.0
        and durations_min[3] is not None and durations_min[3] <= 20,

        d[4] is not None and d[4] >= 1.0
        and speeds[4] is not None and 1.0 <= speeds[4] <= 7.5,
    ]

    if all(checks):
        return ["swim", "transition_1", "bike", "transition_2", "run"]

    return labels


def discipline_metrics(speed_mps, discipline):
    """
    Return only meaningful pace/speed metrics for the discipline:
    run/walk -> min/km; swim -> min/100m; bike -> km/h.
    Multisport parents and transitions do not get fabricated pace values.
    """
    result = {
        "avg_speed_kph": speed_to_kph(speed_mps),
        "avg_pace": None,
        "avg_pace_sec_per_km": None,
        "avg_swim_pace_per_100m": None,
        "avg_swim_pace_sec_per_100m": None,
        "pace_unit": None,
    }

    if discipline in ("run", "walk"):
        pace, pace_sec = speed_to_pace_metrics(speed_mps)
        result["avg_pace"] = pace
        result["avg_pace_sec_per_km"] = pace_sec
        result["pace_unit"] = "min/km"
    elif discipline == "swim":
        pace, pace_sec = swim_speed_to_pace_metrics(speed_mps)
        result["avg_swim_pace_per_100m"] = pace
        result["avg_swim_pace_sec_per_100m"] = pace_sec
        result["pace_unit"] = "min/100m"

    return result


def format_stride_length(val):
    if val is None or val == "N/A" or val == "":
        return None
    try:
        # Garmin API reports stride length in centimeters; convert to meters
        return round(float(val) / 100.0, 4)
    except (ValueError, TypeError):
        return None

def deep_get(source_dict, keys, default=None):
    if not isinstance(source_dict, dict):
        return default
    for key in keys:
        if "." in key:
            parts = key.split(".")
            val = source_dict
            for part in parts:
                if isinstance(val, dict) and part in val:
                    val = val.get(part)
                else:
                    val = None
                    break
            if val is not None and val != "":
                return val
        else:
            if key in source_dict:
                val = source_dict.get(key)
                if val is not None and val != "":
                    return val
    return default


def first_available_metric_key(index_map, exact=(), contains=()):
    """Find a metric descriptor key without assuming Garmin's column order."""
    for key in exact:
        if key in index_map:
            return key

    lower_map = {str(k).lower(): k for k in index_map}
    for token in contains:
        token = token.lower()
        for lower_key, original_key in lower_map.items():
            if token in lower_key:
                return original_key

    return None


def parse_activity_detail_samples(details):
    """
    Parse Garmin get_activity_details() safely.

    Garmin's activityDetailMetrics rows are positional. metricDescriptors
    tells us which metricsIndex belongs to which key; hardcoding indexes is unsafe.
    """
    if not isinstance(details, dict):
        return [], [], {}

    descriptors = details.get("metricDescriptors") or []
    rows = details.get("activityDetailMetrics") or []

    index_map = {}
    descriptor_keys = []

    for desc in descriptors:
        if not isinstance(desc, dict):
            continue
        key = desc.get("key")
        idx = desc.get("metricsIndex")
        if key is None:
            continue
        descriptor_keys.append(str(key))
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            continue
        index_map[str(key)] = idx

    time_key = first_available_metric_key(
        index_map,
        exact=("sumDuration", "sumElapsedDuration", "sumMovingDuration"),
        contains=("duration",),
    )
    distance_key = first_available_metric_key(
        index_map,
        exact=("sumDistance",),
        contains=("distance",),
    )
    hr_key = first_available_metric_key(
        index_map,
        exact=("directHeartRate",),
        contains=("heartrate", "heart_rate", "heart"),
    )
    power_key = first_available_metric_key(
        index_map,
        exact=("directPower",),
        contains=("power",),
    )
    cadence_key = first_available_metric_key(
        index_map,
        exact=("directRunCadence", "directCadence"),
        contains=("cadence",),
    )
    speed_key = first_available_metric_key(
        index_map,
        exact=("directSpeed",),
        contains=("speed",),
    )
    temperature_key = first_available_metric_key(
        index_map,
        exact=("directTemperature",),
        contains=("temperature", "temp"),
    )

    selected = {
        "time": time_key,
        "distance": distance_key,
        "hr": hr_key,
        "power": power_key,
        "cadence": cadence_key,
        "speed": speed_key,
        "temperature": temperature_key,
    }

    samples = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        metrics = row.get("metrics")
        if not isinstance(metrics, list):
            continue

        sample = {}

        for output_key, metric_key in selected.items():
            if metric_key is None:
                sample[output_key] = None
                continue

            idx = index_map.get(metric_key)
            if idx is None or idx < 0 or idx >= len(metrics):
                sample[output_key] = None
                continue

            sample[output_key] = safe_float(metrics[idx], 4)

        # Some Garmin payloads also expose timestamps outside the positional array.
        sample["timestamp"] = deep_get(
            row,
            ["startGMT", "startTimeGMT", "timestamp", "clockTime"],
            None,
        )
        samples.append(sample)

    return samples, descriptor_keys, selected


def normalize_cumulative_series(samples, total_duration_sec=None, total_distance_m=None):
    """
    Normalize Garmin cumulative time/distance to seconds/meters.

    Most devices already return seconds/meters. The scale detection protects
    against millisecond or kilometer-like variants without silently assuming.
    """
    normalized = [dict(s) for s in samples]

    def choose_scale(values, expected, candidates):
        numeric = [float(v) for v in values if v is not None]
        if not numeric or expected is None or expected <= 0:
            return 1.0

        maximum = max(numeric)
        if maximum <= 0:
            return 1.0

        best_scale = 1.0
        best_error = float("inf")

        for scale in candidates:
            scaled = maximum * scale
            error = abs(scaled - expected) / expected
            if error < best_error:
                best_error = error
                best_scale = scale

        return best_scale

    t_scale = choose_scale(
        [s.get("time") for s in normalized],
        total_duration_sec,
        (1.0, 0.001, 60.0),
    )
    d_scale = choose_scale(
        [s.get("distance") for s in normalized],
        total_distance_m,
        (1.0, 1000.0, 0.001),
    )

    for s in normalized:
        if s.get("time") is not None:
            s["time_sec"] = float(s["time"]) * t_scale
        else:
            s["time_sec"] = None

        if s.get("distance") is not None:
            s["distance_m"] = float(s["distance"]) * d_scale
        else:
            s["distance_m"] = None

    return normalized, {"time_scale": t_scale, "distance_scale": d_scale}


def interpolated_boundary_time(samples, target_distance_m):
    """Return interpolated time when local cumulative distance crosses target."""
    if not samples:
        return None

    previous = None
    for sample in samples:
        d = sample.get("local_distance_m")
        t = sample.get("time_sec")
        if d is None or t is None:
            continue

        if d >= target_distance_m:
            if previous is None:
                return t

            pd = previous.get("local_distance_m")
            pt = previous.get("time_sec")
            if pd is None or pt is None or d <= pd:
                return t

            fraction = (target_distance_m - pd) / (d - pd)
            fraction = max(0.0, min(1.0, fraction))
            return pt + fraction * (t - pt)

        previous = sample

    return None


def average_metric_between(samples, key, start_time, end_time):
    vals = [
        s.get(key)
        for s in samples
        if s.get("time_sec") is not None
        and start_time <= s["time_sec"] <= end_time
        and s.get(key) is not None
    ]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def max_metric_between(samples, key, start_time, end_time):
    vals = [
        s.get(key)
        for s in samples
        if s.get("time_sec") is not None
        and start_time <= s["time_sec"] <= end_time
        and s.get(key) is not None
    ]
    if not vals:
        return None
    return round(max(vals), 1)


def derive_fixed_distance_splits(detail_samples, segment_intervals):
    """
    Build analysis-friendly distance splits from Garmin activity-detail samples.

    These are NOT Garmin laps. They are explicitly marked derived:
      swim -> 500 m
      bike -> 5 km
      run  -> 1 km

    Segment boundaries come from the multisport segment durations already
    returned by Garmin.
    """
    if not detail_samples or not segment_intervals:
        return {}

    useful_samples = [
        s for s in detail_samples
        if s.get("time_sec") is not None and s.get("distance_m") is not None
    ]
    if len(useful_samples) < 2:
        return {}

    step_by_discipline = {
        "swim": 500.0,
        "bike": 5000.0,
        "run": 1000.0,
    }

    result = {}
    cumulative_start_sec = 0.0

    for segment in segment_intervals:
        segment_type = segment.get("segment_type")
        duration_min = segment.get("time_min")
        expected_distance_km = segment.get("distance_km")

        if duration_min is None:
            continue

        segment_duration_sec = float(duration_min) * 60.0
        segment_end_sec = cumulative_start_sec + segment_duration_sec

        if (
            segment_type not in step_by_discipline
            or expected_distance_km is None
            or expected_distance_km <= 0
        ):
            cumulative_start_sec = segment_end_sec
            continue

        seg_samples = [
            dict(s)
            for s in useful_samples
            if cumulative_start_sec <= s["time_sec"] <= segment_end_sec
        ]

        if len(seg_samples) < 2:
            cumulative_start_sec = segment_end_sec
            continue

        # Use the first/last recorded cumulative distance in the segment.
        first_distance = seg_samples[0]["distance_m"]
        last_distance = seg_samples[-1]["distance_m"]
        observed_distance = last_distance - first_distance
        expected_distance = float(expected_distance_km) * 1000.0

        if observed_distance <= 0:
            cumulative_start_sec = segment_end_sec
            continue

        # Detail samples at segment boundaries can be a little early/late.
        # Rescale only when observed distance is reasonably close to Garmin's
        # segment summary. Otherwise keep raw distance and flag the mismatch.
        ratio = expected_distance / observed_distance
        use_scale = ratio if 0.80 <= ratio <= 1.20 else 1.0

        for s in seg_samples:
            s["local_distance_m"] = (s["distance_m"] - first_distance) * use_scale

        available_distance = seg_samples[-1]["local_distance_m"]
        split_step = step_by_discipline[segment_type]

        # Prefer the known Garmin segment distance when the rescaling was safe.
        usable_total = expected_distance if use_scale != 1.0 else min(
            expected_distance,
            available_distance,
        )

        boundaries = []
        target = split_step
        while target < usable_total - 1e-6:
            boundaries.append(target)
            target += split_step

        # Include the exact final segment distance as the final boundary.
        boundaries.append(usable_total)

        segment_output = []
        prev_target = 0.0
        prev_time = cumulative_start_sec

        for split_number, boundary in enumerate(boundaries, start=1):
            boundary_time = interpolated_boundary_time(seg_samples, boundary)
            if boundary_time is None or boundary_time <= prev_time:
                continue

            split_distance_m = boundary - prev_target
            split_time_sec = boundary_time - prev_time
            if split_distance_m <= 0 or split_time_sec <= 0:
                continue

            speed_mps = split_distance_m / split_time_sec
            split_metrics = discipline_metrics(speed_mps, segment_type)

            avg_hr = average_metric_between(seg_samples, "hr", prev_time, boundary_time)
            max_hr = max_metric_between(seg_samples, "hr", prev_time, boundary_time)
            avg_power = average_metric_between(seg_samples, "power", prev_time, boundary_time)
            max_power = max_metric_between(seg_samples, "power", prev_time, boundary_time)
            avg_cadence = average_metric_between(seg_samples, "cadence", prev_time, boundary_time)

            segment_output.append({
                "split_number": split_number,
                "source": "derived_from_activity_details",
                "distance_km": round(split_distance_m / 1000.0, 3),
                "cumulative_distance_km": round(boundary / 1000.0, 3),
                "time_min": round(split_time_sec / 60.0, 2),
                "avg_speed_kph": split_metrics["avg_speed_kph"],
                "avg_pace": split_metrics["avg_pace"],
                "avg_pace_sec_per_km": split_metrics["avg_pace_sec_per_km"],
                "avg_swim_pace_per_100m": split_metrics["avg_swim_pace_per_100m"],
                "avg_swim_pace_sec_per_100m": split_metrics["avg_swim_pace_sec_per_100m"],
                "pace_unit": split_metrics["pace_unit"],
                "avg_hr": safe_int(avg_hr),
                "max_hr": safe_int(max_hr),
                "avg_power_w": safe_int(avg_power),
                "max_power_w": safe_int(max_power),
                "avg_cadence": safe_float(avg_cadence, 1),
                "cadence_unit": (
                    "spm" if segment_type == "run"
                    else "rpm" if segment_type == "bike"
                    else None
                ),
            })

            prev_target = boundary
            prev_time = boundary_time

        if segment_output:
            result[segment_type] = {
                "split_definition": (
                    "500m" if segment_type == "swim"
                    else "5km" if segment_type == "bike"
                    else "1km"
                ),
                "source": "derived_from_activity_details",
                "distance_scaling_applied": round(use_scale, 6),
                "observed_detail_distance_km": round(observed_distance / 1000.0, 3),
                "garmin_segment_distance_km": round(expected_distance / 1000.0, 3),
                "splits": segment_output,
            }

        cumulative_start_sec = segment_end_sec

    return result


def safe_get_activity_details(api, activity_id):
    """
    Fetch higher-resolution activity detail samples.
    Falls back to library defaults if Garmin rejects a larger chart request.
    """
    try:
        return api.get_activity_details(activity_id, maxchart=12000, maxpoly=0)
    except Exception:
        try:
            return api.get_activity_details(activity_id)
        except Exception:
            return None


def endpoint_shape(value):
    """Compact diagnostics without dumping large raw Garmin payloads."""
    if value is None:
        return {"available": False}

    info = {
        "available": True,
        "type": type(value).__name__,
    }

    if isinstance(value, dict):
        info["keys"] = list(value.keys())[:30]
        for key in ("lapDTOs", "splitDTOs", "activityDetailMetrics", "metricDescriptors"):
            item = value.get(key)
            if isinstance(item, list):
                info[f"{key}_count"] = len(item)
    elif isinstance(value, list):
        info["count"] = len(value)

    return info


def main():
    # Force Philippine Time (UTC+8) so cron jobs running on UTC servers pick up the correct local date
    ph_today = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description="Fetch Garmin health, single-sport, and multisport telemetry with discipline-correct metrics.")
    parser.add_argument("--date", type=str, default=ph_today, help="Date in YYYY-MM-DD format (defaults to today in Manila time)")
    args = parser.parse_args()
    target_date_str = args.date

    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid date format provided: '{target_date_str}'. Please use YYYY-MM-DD format.") from e

    garmin_tokens_json = os.environ.get("GARMIN_TOKENS_JSON")
    if not garmin_tokens_json:
        raise ValueError("GARMIN_TOKENS_JSON environment variable is missing.")

    token_dir = "./.garminconnect"
    os.makedirs(token_dir, exist_ok=True)
    with open(os.path.join(token_dir, "garmin_tokens.json"), "w") as f:
        f.write(garmin_tokens_json)

    api = Garmin()
    api.login(token_dir)

    # 1. FETCH HISTORICAL ACTIVITIES FOR VOLUME CALCULATIONS (Past 28 Days)
    start_history_date = target_date - timedelta(days=27)
    try:
        historical_activities = api.get_activities_by_date(
            start_history_date.isoformat(), 
            target_date.isoformat()
        )
    except Exception:
        historical_activities = []

    running_activities = []
    for act in historical_activities:
        act_type = deep_get(act, ["activityType.typeKey", "activityType"], "").lower()
        if "run" in act_type:
            start_str = act.get("startTimeLocal", "")
            try:
                act_date = datetime.strptime(start_str.split(" ")[0], "%Y-%m-%d").date()
                dist_km = (act.get("distance", 0) or 0) / 1000.0
                running_activities.append({"date": act_date, "distance_km": dist_km})
            except Exception:
                pass

    seven_days_ago = target_date - timedelta(days=6)
    dist_7_days = sum(a["distance_km"] for a in running_activities if seven_days_ago <= a["date"] <= target_date)

    weekly_distances = []
    for i in range(4):
        week_end = target_date - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=6)
        w_dist = sum(a["distance_km"] for a in running_activities if week_start <= a["date"] <= week_end)
        weekly_distances.append(round(w_dist, 1))

    weekly_distances.reverse()
    avg_28_day_weekly = round(sum(weekly_distances) / len(weekly_distances), 1) if weekly_distances else 0.0

    training_history = {
        "7_day_distance_km": round(dist_7_days, 1),
        "28_day_avg_weekly_distance_km": avg_28_day_weekly,
        "weekly_distance_last_4_weeks_km": weekly_distances
    }

    # 2. FETCH HEALTH & READINESS METRICS FOR TARGET DATE
    stats = api.get_stats(target_date_str)
    rhr = safe_int(deep_get(stats, ["restingHeartRate", "rhr"]))
    total_steps = safe_int(deep_get(stats, ["totalSteps", "steps"]))
    body_battery_morning = safe_int(deep_get(stats, ["bodyBatteryMostRecent", "bodyBatteryMorning", "bodyBatteryValues"]))
    recovery_time_hours = safe_float(deep_get(stats, ["recoveryTime", "recoveryTimeHours"]))
    
    sleep_data = api.get_sleep_data(target_date_str)
    sleep_dto = sleep_data.get("dailySleepDTO", {}) if isinstance(sleep_data, dict) else {}
    sleep_score = safe_int(deep_get(sleep_dto, ["sleepScores.overall.value", "overallSleepScore", "sleepScore"]))
    sleep_duration_sec = deep_get(sleep_dto, ["sleepTimeSeconds", "durationInSeconds"])
    total_sleep_hours = round(sleep_duration_sec / 3600.0, 2) if sleep_duration_sec else None
    
    deep_sec = deep_get(sleep_dto, ["deepSleepSeconds", "sleepMetrics.deepSleepSeconds"])
    light_sec = deep_get(sleep_dto, ["lightSleepSeconds", "sleepMetrics.lightSleepSeconds"])
    rem_sec = deep_get(sleep_dto, ["remSleepSeconds", "sleepMetrics.remSleepSeconds"])
    awake_sec = deep_get(sleep_dto, ["awakeSleepSeconds", "sleepMetrics.awakeSleepSeconds"])

    sleep_stages_hours = {
        "deep": round(deep_sec / 3600.0, 2) if deep_sec is not None else None,
        "light": round(light_sec / 3600.0, 2) if light_sec is not None else None,
        "rem": round(rem_sec / 3600.0, 2) if rem_sec is not None else None,
        "awake": round(awake_sec / 3600.0, 2) if awake_sec is not None else None
    }

    # HRV Extraction
    hrv_status, hrv_last, hrv_weekly_avg = None, None, None
    baseline_balanced_range = None
    try:
        hrv_data = api.get_hrv_data(target_date_str)
        hrv_summary = hrv_data.get("hrvSummary", {}) if isinstance(hrv_data, dict) else {}
        hrv_status = deep_get(hrv_summary, ["status", "hrvStatus"])
        hrv_last = safe_int(deep_get(hrv_summary, ["lastNightAvg", "weeklyAvg", "bal"]))
        hrv_weekly_avg = safe_int(deep_get(hrv_summary, ["weeklyAvg", "sevenDayAvg", "sevenDayAverage", "lastSevenDaysAvg"]))
        
        baseline_obj = hrv_summary.get("baseline", {})
        if isinstance(baseline_obj, dict):
            low = safe_int(baseline_obj.get("balancedLow"))
            upper = safe_int(baseline_obj.get("balancedUpper"))
            if low is not None and upper is not None:
                baseline_balanced_range = {"balanced_low": low, "balanced_upper": upper}
    except Exception:
        pass

    # Training Status & Max Metrics Extraction
    acute_load, load_ratio, vo2_max = None, None, None
    lthr_bpm, lt_pace, lt_pace_sec = None, None, None

    try:
        training_status = api.get_training_status(target_date_str)
        if training_status:
            acute_load = safe_float(deep_get(training_status, ["acuteLoad", "load", "currentAcuteLoad", "trainingLoadDTO.acuteLoad"]))
            load_ratio = safe_float(deep_get(training_status, ["loadRatio", "acuteChronicWorkloadRatio", "loadRatioValue"]))
    except Exception:
        pass

    try:
        max_metrics = api.get_max_metrics(target_date_str)
        if isinstance(max_metrics, list) and len(max_metrics) > 0:
            m_item = max_metrics[0]
            vo2_max = safe_float(deep_get(m_item, ["vo2MaxValue", "vo2Max", "generic.vo2MaxValue"]))
            lthr_bpm = safe_int(deep_get(m_item, ["lactateThresholdHeartRate", "lthr", "running.lactateThresholdHeartRate"]))
            lt_speed = deep_get(m_item, ["lactateThresholdSpeed", "ltSpeed", "running.lactateThresholdSpeed"], None)
            if lt_speed and lt_speed > 0:
                lt_pace, lt_pace_sec = speed_to_pace_metrics(lt_speed)
    except Exception:
        pass

    health_metrics = {
        "resting_hr": rhr,
        "hrv": {
            "last_night_avg_ms": hrv_last,
            "seven_day_avg_ms": hrv_weekly_avg,
            "status": hrv_status,
            "baseline_balanced_range": baseline_balanced_range
        },
        "sleep_score": sleep_score,
        "total_sleep_hours": total_sleep_hours,
        "sleep_stages_hours": sleep_stages_hours,
        "respiration_rate_sleep": safe_float(deep_get(sleep_dto, ["averageRespiration", "respiration"])),
        "body_battery_morning": body_battery_morning,
        "recovery_time_hours": recovery_time_hours,
        "training_readiness": safe_int(deep_get(stats, ["trainingReadiness"])),
        "training_status": {
            "acute_load": acute_load,
            "load_ratio": load_ratio,
            "vo2_max": vo2_max,
            "lthr_bpm": lthr_bpm,
            "lt_pace": lt_pace,
            "lt_pace_sec_per_km": lt_pace_sec
        },
        "total_steps": total_steps
    }

    # 3. TOP-LEVEL SUBJECTIVE BLOCK (Manual entry templates)
    subjective_block = {
        "leg_soreness_0_10": None,
        "leg_heaviness_0_10": None,
        "overall_fatigue_0_10": None,
        "motivation_0_10": None,
        "notes": None
    }

    # 4. FETCH TARGET DATE ACTIVITIES & INTERVALS
    try:
        activities = api.get_activities_by_date(target_date_str, target_date_str)
    except Exception:
        activities = []

    activities_list = []
    for act in activities:
        act_id = act.get("activityId")
        act_type_raw = deep_get(act, ["activityType.typeKey", "activityType"], "running")
        act_type = str(act_type_raw).lower() if act_type_raw is not None else "running"
        discipline = normalize_discipline(act_type)

        is_running = discipline == "run"
        is_walking = discipline == "walk"
        is_cycling = discipline == "bike"
        is_swimming = discipline == "swim"
        is_strength = discipline == "strength"
        is_multisport = discipline == "multi_sport"

        avg_speed_mps = act.get("averageSpeed", None)
        parent_metrics = discipline_metrics(avg_speed_mps, discipline)

        # GAP is meaningful for run/walk only.
        avg_gap_mps = deep_get(act, ["averageGradeAdjustedSpeed", "gradeAdjustedSpeed"], None)
        avg_gap_str, avg_gap_sec = (
            speed_to_pace_metrics(avg_gap_mps)
            if avg_gap_mps and discipline in ("run", "walk")
            else (None, None)
        )

        raw_stride = deep_get(act, ["avgStrideLength", "averageStrideLength", "strideLength"], None)
        avg_stride_m = format_stride_length(raw_stride) if discipline in ("run", "walk") else None

        # Cadence: SPM for run/walk, RPM for bike.
        if discipline in ("run", "walk"):
            avg_cadence = safe_int(deep_get(
                act,
                ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence"],
            ))
        elif discipline == "bike":
            avg_cadence = safe_int(deep_get(
                act,
                ["averageBikingCadenceInRPM", "averageBikeCadence", "averageCadence"],
            ))
        else:
            avg_cadence = safe_int(deep_get(act, ["averageCadence"]))

        summary = {
            "activity_id": act_id,
            "activity_type": act_type,
            "discipline": discipline,
            "activity_name": deep_get(act, ["activityName"]),
            "start_time": deep_get(act, ["startTimeLocal"]),
            # Garmin distance is meters for every discipline; output is always km.
            "total_distance_km": round(act.get("distance", 0) / 1000.0, 3) if act.get("distance") is not None else None,
            "total_duration_min": round(act.get("duration", 0) / 60.0, 2) if act.get("duration") else None,
            "moving_duration_min": round(act.get("movingDuration", 0) / 60.0, 2) if act.get("movingDuration") else None,
            "run_time_min": round(act.get("movingDuration", 0) / 60.0, 2) if is_running and act.get("movingDuration") else None,
            "walk_time_min": round(act.get("movingDuration", 0) / 60.0, 2) if is_walking and act.get("movingDuration") else None,
            "idle_time_min": None,
            "avg_speed_kph": parent_metrics["avg_speed_kph"],
            "avg_pace": parent_metrics["avg_pace"],
            "avg_pace_sec_per_km": parent_metrics["avg_pace_sec_per_km"],
            "avg_swim_pace_per_100m": parent_metrics["avg_swim_pace_per_100m"],
            "avg_swim_pace_sec_per_100m": parent_metrics["avg_swim_pace_sec_per_100m"],
            "pace_unit": parent_metrics["pace_unit"],
            "avg_gap": avg_gap_str,
            "avg_gap_sec_per_km": avg_gap_sec,
            "avg_hr": safe_int(deep_get(act, ["averageHR", "avgHR"])),
            "max_hr": safe_int(deep_get(act, ["maxHR", "maximumHR"])),
            "avg_power_w": safe_int(deep_get(act, ["averagePower", "avgPower"])),
            "max_power_w": safe_int(deep_get(act, ["maxPower", "maximumPower"])),
            "normalized_power_w": safe_int(deep_get(act, ["normalizedPower", "normPower"])),
            "avg_cadence": avg_cadence,
            "avg_gct_ms": safe_int(deep_get(act, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"])) if is_running else None,
            "avg_stride_length_m": avg_stride_m,
            "avg_vertical_oscillation_cm": safe_float(deep_get(act, ["avgVerticalOscillation", "averageVerticalOscillation", "verticalOscillation"])) if is_running else None,
            "avg_vertical_ratio_pct": safe_float(deep_get(act, ["avgVerticalRatio", "verticalRatio"])) if is_running else None,
            "elevation_gain_m": safe_float(deep_get(act, ["elevationGain", "totalAscent"])),
            "elevation_loss_m": safe_float(deep_get(act, ["elevationLoss", "totalDescent"])),
            "avg_temperature_c": safe_float(deep_get(act, ["averageTemperature", "minTemperature", "temperature"])),
            "primary_benefit": deep_get(act, ["primaryBenefit", "trainingEffectLabel"]),
            "aerobic_te": safe_float(deep_get(act, ["aerobicTrainingEffect"])),
            "aerobic_te_label": deep_get(act, ["aerobicTrainingEffectMessage"]),
            "anaerobic_te": safe_float(deep_get(act, ["anaerobicTrainingEffect"])),
            "anaerobic_te_label": deep_get(act, ["anaerobicTrainingEffectMessage"]),
            "exercise_load": safe_int(deep_get(act, ["exerciseLoad", "activityTrainingLoad"])),
            "impact_load_km": safe_float(deep_get(act, ["impactLoad"])) if is_running else None,
            "calories": safe_int(deep_get(act, ["calories"])),
            "session_rpe_0_10": None
        }

        intervals = []
        if act_id and not is_strength:
            try:
                splits = api.get_activity_splits(act_id)
                lap_dtos = splits.get("lapDTOs", []) if isinstance(splits, dict) else []

                # Prefer Garmin's per-lap sport metadata. If Garmin omitted it,
                # infer only an obvious standard five-part triathlon.
                inferred_segments = (
                    infer_triathlon_segment_types(lap_dtos)
                    if is_multisport
                    else [None] * len(lap_dtos)
                )

                for idx, lap in enumerate(lap_dtos, start=1):
                    l_dist = (
                        round(lap.get("distance", 0) / 1000.0, 3)
                        if lap.get("distance") is not None
                        else None
                    )
                    l_speed = lap.get("averageSpeed", None)

                    api_lap_discipline = lap_discipline_from_api(lap)
                    inferred_segment = (
                        inferred_segments[idx - 1]
                        if idx - 1 < len(inferred_segments)
                        else None
                    )

                    segment_type = api_lap_discipline or inferred_segment
                    metric_discipline = (
                        "transition"
                        if segment_type in ("transition", "transition_1", "transition_2")
                        else segment_type
                    )

                    # Single-sport laps often omit their sport metadata.
                    if metric_discipline is None and not is_multisport:
                        metric_discipline = discipline
                        segment_type = discipline

                    lap_metrics = discipline_metrics(l_speed, metric_discipline)

                    l_gap_speed = deep_get(lap, ["averageGradeAdjustedSpeed", "gradeAdjustedSpeed"], None)
                    l_gap_pace, l_gap_sec = (
                        speed_to_pace_metrics(l_gap_speed)
                        if l_gap_speed and metric_discipline in ("run", "walk")
                        else (None, None)
                    )

                    raw_lap_stride = deep_get(lap, ["avgStrideLength", "strideLength", "averageStrideLength"], None)
                    lap_stride_m = (
                        format_stride_length(raw_lap_stride)
                        if metric_discipline in ("run", "walk")
                        else None
                    )

                    if metric_discipline in ("run", "walk"):
                        lap_cadence = safe_int(deep_get(
                            lap,
                            ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence"],
                        ))
                    elif metric_discipline == "bike":
                        lap_cadence = safe_int(deep_get(
                            lap,
                            ["averageBikingCadenceInRPM", "averageBikeCadence", "averageCadence"],
                        ))
                    else:
                        lap_cadence = safe_int(deep_get(lap, ["averageCadence"]))

                    # Workout step type is separate from multisport segment type.
                    raw_step_type = lap.get("stepType")
                    if raw_step_type is not None:
                        step_type_raw = str(raw_step_type)
                        clean_raw = step_type_raw.strip().capitalize()
                        if metric_discipline == "walk" and clean_raw in ["Run", "Interval"]:
                            step_type = "Walk"
                        else:
                            step_type = clean_raw
                    else:
                        step_type = None
                        step_type_raw = None

                    intervals.append({
                        "interval_number": idx,
                        "segment_type": segment_type,
                        "discipline": metric_discipline,
                        "segment_type_source": (
                            "garmin"
                            if api_lap_discipline is not None
                            else "inferred"
                            if inferred_segment is not None
                            else "parent_activity"
                            if not is_multisport
                            else None
                        ),
                        "step_type": step_type,
                        "step_type_raw": step_type_raw,
                        "lap_trigger": deep_get(lap, ["lapTrigger"]),
                        "time_min": round(lap.get("duration", 0) / 60.0, 2) if lap.get("duration") else None,
                        "moving_time_min": round(lap.get("movingDuration", 0) / 60.0, 2) if lap.get("movingDuration") else None,
                        "distance_km": l_dist,
                        "avg_speed_kph": lap_metrics["avg_speed_kph"],
                        "avg_pace": lap_metrics["avg_pace"],
                        "avg_pace_sec_per_km": lap_metrics["avg_pace_sec_per_km"],
                        "avg_swim_pace_per_100m": lap_metrics["avg_swim_pace_per_100m"],
                        "avg_swim_pace_sec_per_100m": lap_metrics["avg_swim_pace_sec_per_100m"],
                        "pace_unit": lap_metrics["pace_unit"],
                        "avg_gap": l_gap_pace,
                        "avg_gap_sec_per_km": l_gap_sec,
                        "avg_hr": safe_int(deep_get(lap, ["averageHR", "avgHR"])),
                        "max_hr": safe_int(deep_get(lap, ["maxHR", "maximumHR"])),
                        "power_w": safe_int(deep_get(lap, ["averagePower", "avgPower", "power"])),
                        "max_power_w": safe_int(deep_get(lap, ["maxPower", "maximumPower"])),
                        "normalized_power_w": safe_int(deep_get(lap, ["normalizedPower", "normPower"])),
                        "cadence": lap_cadence,
                        "cadence_unit": (
                            "spm"
                            if metric_discipline in ("run", "walk")
                            else "rpm"
                            if metric_discipline == "bike"
                            else None
                        ),
                        "avg_gct_ms": safe_int(deep_get(
                            lap,
                            ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"],
                        )) if metric_discipline == "run" else None,
                        "avg_stride_length_m": lap_stride_m,
                        "vertical_oscillation_cm": safe_float(deep_get(
                            lap,
                            ["verticalOscillation", "avgVerticalOscillation"],
                        )) if metric_discipline == "run" else None,
                        "vertical_ratio_pct": safe_float(deep_get(
                            lap,
                            ["verticalRatio", "avgVerticalRatio"],
                        )) if metric_discipline == "run" else None,
                        "elevation_gain_m": safe_float(deep_get(lap, ["elevationGain", "totalAscent"])),
                        "elevation_loss_m": safe_float(deep_get(lap, ["elevationLoss", "totalDescent"])),
                        "avg_temperature_c": safe_float(deep_get(lap, ["averageTemperature", "temperature"])),
                    })
            except Exception:
                pass

        # 5. FETCH DEEPER SPLIT SOURCES + ACTIVITY DETAIL TIME SERIES
        typed_splits_raw = None
        split_summaries_raw = None
        activity_details_raw = None

        if act_id and not is_strength:
            try:
                typed_splits_raw = api.get_activity_typed_splits(act_id)
            except Exception:
                typed_splits_raw = None

            try:
                split_summaries_raw = api.get_activity_split_summaries(act_id)
            except Exception:
                split_summaries_raw = None

            activity_details_raw = safe_get_activity_details(api, act_id)

        detail_samples = []
        detail_descriptor_keys = []
        detail_selected_metrics = {}
        detail_scale_info = None

        if activity_details_raw:
            (
                detail_samples,
                detail_descriptor_keys,
                detail_selected_metrics,
            ) = parse_activity_detail_samples(activity_details_raw)

            expected_duration_sec = (
                float(summary["total_duration_min"]) * 60.0
                if summary.get("total_duration_min") is not None
                else None
            )
            expected_distance_m = (
                float(summary["total_distance_km"]) * 1000.0
                if summary.get("total_distance_km") is not None
                else None
            )

            detail_samples, detail_scale_info = normalize_cumulative_series(
                detail_samples,
                total_duration_sec=expected_duration_sec,
                total_distance_m=expected_distance_m,
            )

        discipline_splits = (
            derive_fixed_distance_splits(detail_samples, intervals)
            if is_multisport
            else {}
        )

        split_source_diagnostics = {
            "regular_splits": {
                "available": bool(intervals),
                "count": len(intervals),
            },
            "typed_splits": endpoint_shape(typed_splits_raw),
            "split_summaries": endpoint_shape(split_summaries_raw),
            "activity_details": endpoint_shape(activity_details_raw),
            "activity_detail_descriptor_keys": detail_descriptor_keys,
            "activity_detail_selected_metrics": detail_selected_metrics,
            "activity_detail_sample_count": len(detail_samples),
            "activity_detail_scaling": detail_scale_info,
            "derived_discipline_splits_available": sorted(discipline_splits.keys()),
        }

        # Direct convenience view for standard triathlon segments.
        segments = {}
        if is_multisport:
            for item in intervals:
                seg = item.get("segment_type")
                if seg in ("swim", "transition_1", "bike", "transition_2", "run"):
                    segments[seg] = item

        activities_list.append({
            "summary": summary,
            "segments": segments if segments else None,
            "discipline_splits": discipline_splits if discipline_splits else None,
            "split_source_diagnostics": split_source_diagnostics,
            "intervals": intervals
        })

    payload = {
        "date": target_date_str,
        "training_history": training_history,
        "health_metrics": health_metrics,
        "subjective": subjective_block,
        "activities": activities_list
    }

    os.makedirs("data", exist_ok=True)
    file_path = os.path.join("data", f"garmin_{target_date_str}.json")
    with open(file_path, "w") as f:
        json.dump(payload, f, indent=4)
    print(f"Successfully generated deep multi-sport JSON for {target_date_str} at: {file_path}")

if __name__ == "__main__":
    main()

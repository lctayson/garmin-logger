import os
import sys
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

def deep_get(source_dict, keys, default=None):
    if not isinstance(source_dict, dict):
        return default

    for key in keys:
        val = source_dict
        success = True
        
        for part in key.split("."):
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                success = False
                break
        
        if success and val is not None and val != "":
            return val

    return default

def format_pace(distance_m, duration_sec, activity_type="run"):
    """Format pace as MM:SS (per km for run/walk, per 100m for swim). Returns None for cycling/others."""
    if not distance_m or not duration_sec or distance_m <= 0 or duration_sec <= 0:
        return None

    activity_type_lower = (activity_type or "").lower()

    if "swim" in activity_type_lower:
        sec_per_unit = (duration_sec / distance_m) * 100
    elif any(t in activity_type_lower for t in ["cycle", "biking", "bike"]):
        return None
    else:
        sec_per_unit = (duration_sec / distance_m) * 1000

    total_sec = int(round(sec_per_unit))
    mins = total_sec // 60
    secs = total_sec % 60
    return f"{mins}:{secs:02d}"

def get_training_history(api, target_date):
    """Fetch and calculate training history distance metrics over the past 28 days."""
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

    return {
        "7_day_distance_km": round(dist_7_days, 1),
        "28_day_avg_weekly_distance_km": avg_28_day_weekly,
        "weekly_distance_last_4_weeks_km": weekly_distances
    }

def get_health_stats(api, target_date_str):
    """Fetch and format daily health stats: resting HR, HRV, sleep."""
    stats = {}
    try:
        stats = api.get_stats(target_date_str)
    except Exception:
        pass

    rhr = safe_int(stats.get("restingHeartRate") or stats.get("rhr"))
    total_steps = safe_int(stats.get("totalSteps") or stats.get("steps"))

    sleep_data = {}
    try:
        sleep_data = api.get_sleep_data(target_date_str)
    except Exception:
        pass

    sleep_dto = sleep_data.get("dailySleepDTO", {}) if isinstance(sleep_data, dict) else {}
    sleep_score = safe_int(
        sleep_dto.get("sleepScores", {}).get("overall", {}).get("value") or
        sleep_dto.get("overallSleepScore") or
        sleep_dto.get("sleepScore")
    )
    sleep_duration_sec = sleep_dto.get("sleepTimeSeconds") or sleep_dto.get("durationInSeconds")
    total_sleep_hours = round(sleep_duration_sec / 3600.0, 2) if sleep_duration_sec else None

    deep_sec = sleep_dto.get("deepSleepSeconds")
    light_sec = sleep_dto.get("lightSleepSeconds")
    rem_sec = sleep_dto.get("remSleepSeconds")
    awake_sec = sleep_dto.get("awakeSleepSeconds")

    sleep_stages_hours = {
        "deep": round(deep_sec / 3600.0, 2) if deep_sec is not None else None,
        "light": round(light_sec / 3600.0, 2) if light_sec is not None else None,
        "rem": round(rem_sec / 3600.0, 2) if rem_sec is not None else None,
        "awake": round(awake_sec / 3600.0, 2) if awake_sec is not None else None
    }

    hrv_last, hrv_weekly_avg, hrv_status, baseline_balanced_range = None, None, None, None
    try:
        hrv_data = api.get_hrv_data(target_date_str)
        hrv_summary = hrv_data.get("hrvSummary", {}) if isinstance(hrv_data, dict) else {}
        hrv_status = hrv_summary.get("status") or hrv_summary.get("hrvStatus")
        hrv_last = safe_int(hrv_summary.get("lastNightAvg") or hrv_summary.get("weeklyAvg"))
        hrv_weekly_avg = safe_int(hrv_summary.get("weeklyAvg") or hrv_summary.get("sevenDayAvg") or hrv_summary.get("lastSevenDaysAvg"))

        baseline_obj = hrv_summary.get("baseline", {})
        if isinstance(baseline_obj, dict):
            low_upper = safe_int(baseline_obj.get("lowUpper"))
            balanced_low = safe_int(baseline_obj.get("balancedLow"))
            balanced_upper = safe_int(baseline_obj.get("balancedUpper"))
            marker_value = safe_float(baseline_obj.get("markerValue"), 7)
            baseline_balanced_range = {
                "lowUpper": low_upper,
                "balancedLow": balanced_low,
                "balancedUpper": balanced_upper,
                "markerValue": marker_value
            }
    except Exception:
        pass

    return {
        "resting_heart_rate": rhr,
        "hrv": {
            "last_night_avg_ms": hrv_last,
            "seven_day_avg_ms": hrv_weekly_avg,
            "status": hrv_status,
            "baseline_balanced_range": baseline_balanced_range
        },
        "sleep_score": sleep_score,
        "total_sleep_hours": total_sleep_hours,
        "sleep_stages_hours": {k: v for k, v in sleep_stages_hours.items() if v is not None},
        "total_steps": total_steps
    }

def humanize_enum(s):
    """Turn a Garmin ALL_CAPS_ENUM string (e.g. 'ANAEROBIC_DEFICIENT') into a
    human-readable label ('Anaerobic Deficient'). Leaves already-readable
    strings untouched."""
    if not isinstance(s, str) or not s:
        return None
    return s.replace("_", " ").strip().title()

def get_training_status_details(api, target_date_str):
    """Fetch the Garmin Connect 'Training Status' widget: overall status,
    Load Focus, Acute/Chronic Training Load + ACWR, Heat/Altitude
    Acclimation, VO2max, and Recovery time."""
    try:
        raw = api.get_training_status(target_date_str)
    except Exception as e:
        print(f"[training_status] Warning: could not fetch training status: {e}", file=sys.stderr)
        return {}

    if not isinstance(raw, dict):
        return {}

    result = {}

    # --- Overall training status (e.g. "Productive 5") ---
    status_block = raw.get("mostRecentTrainingStatus", {}) or {}
    device_map = status_block.get("latestTrainingStatusData", {}) or {}
    device_entry = next(iter(device_map.values()), {}) if isinstance(device_map, dict) else {}

    feedback_phrase = device_entry.get("trainingStatusFeedbackPhrase")
    if feedback_phrase:
        parts = feedback_phrase.split("_")
        status_base = parts[0].title()
        status_level = parts[1] if len(parts) > 1 else ""
        result["status"] = f"{status_base} {status_level}".strip()
    else:
        # Fallback numeric code map if feedback phrase is missing
        TRAINING_STATUS_CODE_MAP = {
            0: "No Status", 1: "Detraining", 2: "Recovery", 3: "Maintaining",
            4: "Productive", 5: "Peaking", 6: "Overreaching", 7: "Unproductive", 8: "Strained"
        }
        raw_code = device_entry.get("trainingStatus")
        code = safe_int(raw_code)
        if code is not None and code in TRAINING_STATUS_CODE_MAP:
            result["status"] = TRAINING_STATUS_CODE_MAP[code]
        else:
            result["status"] = raw_code

    # --- Acute/Chronic training load + ACWR ---
    # BUGFIX: Garmin nests these fields under device_entry["acuteTrainingLoadDTO"],
    # NOT directly on device_entry. The previous version looked at the wrong
    # level and silently returned nothing for acute_training_load in most cases.
    acute_dto = device_entry.get("acuteTrainingLoadDTO", {}) or {}

    acute_load = acute_dto.get("dailyTrainingLoadAcute")
    chronic_load = acute_dto.get("dailyTrainingLoadChronic")
    chronic_load_min = acute_dto.get("minTrainingLoadChronic")
    chronic_load_max = acute_dto.get("maxTrainingLoadChronic")
    acwr_ratio = acute_dto.get("dailyAcuteChronicWorkloadRatio")
    acwr_percent = acute_dto.get("acwrPercent")
    acwr_status = acute_dto.get("acwrStatus")

    if any(v is not None for v in [acute_load, chronic_load, acwr_ratio, acwr_status]):
        result["training_load"] = {
            "acute_load": safe_int(acute_load),
            "chronic_load": safe_int(chronic_load),
            "chronic_load_range": {
                "min": safe_float(chronic_load_min, 1),
                "max": safe_float(chronic_load_max, 1)
            } if (chronic_load_min is not None or chronic_load_max is not None) else None,
            "acwr": safe_float(acwr_ratio, 2),
            "acwr_percent": safe_int(acwr_percent),
            "acwr_status": humanize_enum(acwr_status) if isinstance(acwr_status, str) else acwr_status
        }
        result["training_load"] = {k: v for k, v in result["training_load"].items() if v is not None}

    # --- Recovery time (hours until recovered, as shown on the watch) ---
    recovery_hours = (
        device_entry.get("recoveryTime")
        or device_entry.get("recoveryTimeHours")
        or deep_get(raw, ["mostRecentTrainingLoadBalance.recoveryTime"])
    )
    if recovery_hours is not None:
        result["recovery_time_hours"] = safe_int(recovery_hours)

    # --- Load focus (e.g. "Anaerobic Shortage") ---
    balance_block = raw.get("mostRecentTrainingLoadBalance", {}) or {}
    balance_map = balance_block.get("metricsTrainingLoadBalanceDTOMap", {}) or {}
    balance_entry = next(iter(balance_map.values()), {}) if isinstance(balance_map, dict) else {}
    load_focus_raw = (
        balance_entry.get("trainingLoadBalanceFeedbackPhrase")
        or balance_entry.get("trainingBalanceFeedbackPhrase")
    )
    if load_focus_raw:
        result["load_focus"] = humanize_enum(load_focus_raw) if isinstance(load_focus_raw, str) else load_focus_raw

    # Also surface the monthly aerobic/anaerobic load targets vs actuals from
    # the same balance block -- this is what tells you e.g. "0 anaerobic load
    # this month against a 217-652 target", which the old script dropped.
    if balance_entry:
        monthly_load = {
            "aerobic_low": safe_float(balance_entry.get("monthlyLoadAerobicLow"), 1),
            "aerobic_low_target_min": safe_int(balance_entry.get("monthlyLoadAerobicLowTargetMin")),
            "aerobic_low_target_max": safe_int(balance_entry.get("monthlyLoadAerobicLowTargetMax")),
            "aerobic_high": safe_float(balance_entry.get("monthlyLoadAerobicHigh"), 1),
            "aerobic_high_target_min": safe_int(balance_entry.get("monthlyLoadAerobicHighTargetMin")),
            "aerobic_high_target_max": safe_int(balance_entry.get("monthlyLoadAerobicHighTargetMax")),
            "anaerobic": safe_float(balance_entry.get("monthlyLoadAnaerobic"), 1),
            "anaerobic_target_min": safe_int(balance_entry.get("monthlyLoadAnaerobicTargetMin")),
            "anaerobic_target_max": safe_int(balance_entry.get("monthlyLoadAnaerobicTargetMax")),
        }
        monthly_load = {k: v for k, v in monthly_load.items() if v is not None}
        if monthly_load:
            result["monthly_load_balance"] = monthly_load

    # --- VO2max (value, + qualitative label like "Excellent" IF Garmin's API
    # actually includes it). Grouped together to match how Garmin Connect
    # presents it, sourced from this same training-status response -- no
    # separate get_max_metrics() call needed.
    vo2_block = raw.get("mostRecentVO2Max", {}) or {}
    vo2_generic = vo2_block.get("generic", {}) if isinstance(vo2_block.get("generic"), dict) else {}
    vo2_value = safe_float(deep_get(vo2_generic, ["vo2MaxValue", "vo2MaxPreciseValue", "vo2Max"]))
    vo2_status = (
        vo2_generic.get("vo2MaxStatus")
        or vo2_generic.get("fitnessLevel")
        or vo2_generic.get("vo2MaxCategory")
        or vo2_generic.get("category")
        or deep_get(vo2_block, ["vo2MaxStatus", "fitnessLevel"])
    )

    if vo2_value is not None or vo2_status:
        vo2_max_obj = {}
        if vo2_value is not None:
            vo2_max_obj["value"] = vo2_value
        if vo2_status:
            vo2_max_obj["status"] = humanize_enum(vo2_status) if isinstance(vo2_status, str) else vo2_status
        result["vo2_max"] = vo2_max_obj

    # --- Heat / altitude acclimation (e.g. 100%, "Acclimatized") ---
    heat_block = raw.get("mostRecentVO2Max", {}).get("heatAltitudeAcclimation", {}) or raw.get("heatAltitudeAcclimation", {}) or {}
    heat_pct = heat_block.get("heatAcclimationPercentage")
    heat_trend = heat_block.get("heatTrend")
    altitude_pct = heat_block.get("altitudeAcclimationPercentage") or heat_block.get("acclimationPercentage")
    altitude_trend = heat_block.get("altitudeTrend")
    if heat_pct is not None or heat_trend:
        result["heat_acclimation"] = {
            "percentage": safe_int(heat_pct),
            "trend": humanize_enum(heat_trend) if isinstance(heat_trend, str) else heat_trend
        }
    if altitude_pct is not None or altitude_trend:
        result["altitude_acclimation"] = {
            "percentage": safe_int(altitude_pct),
            "trend": humanize_enum(altitude_trend) if isinstance(altitude_trend, str) else altitude_trend
        }

    cleaned = {k: v for k, v in result.items() if v is not None}
    cleaned = {
        k: v for k, v in cleaned.items()
        if not (isinstance(v, dict) and not any(vv is not None for vv in v.values()))
    }

    if not cleaned:
        print(
            f"[training_status] Warning: no recognizable fields extracted from "
            f"get_training_status() response. Top-level keys returned: "
            f"{list(raw.keys())}. Field-name mapping may need adjustment.",
            file=sys.stderr
        )

    return cleaned

def get_metric_trend(api, target_date, days=14, interval=1):
    """Build a trend series (RHR, HRV, sleep, VO2max, training load/ACWR,
    training status) sampled every `interval` days over the trailing `days`
    days. This is what lets a coach see direction of travel -- e.g. is
    VO2max rising or flat, is chronic load actually where it should be, is
    HRV trending down across a week -- rather than a single noisy snapshot.

    `interval` controls resolution vs. API call cost:
    - interval=1 (daily): needed for genuinely noisy day-to-day metrics
      like HRV/RHR/sleep over a short window (5-14 days).
    - interval=7 (weekly): appropriate for slow-moving metrics like VO2max
      and 28-day-rolling chronic load over a long window (8-12+ weeks) --
      daily sampling there just measures a smooth number with more calls
      than the data actually has resolution to support.

    Note: this makes ~2 API calls per SAMPLED day, so days=84, interval=7
    makes ~24 calls (12 weekly points), not ~168.
    """
    sample_offsets = list(range(0, days, interval))
    if sample_offsets and sample_offsets[-1] != days - 1:
        sample_offsets.append(days - 1)  # always include the most recent day

    trend = []
    for offset in sample_offsets:
        d = target_date - timedelta(days=days - 1 - offset)
        d_str = d.isoformat()
        try:
            health = get_health_stats(api, d_str)
        except Exception:
            health = {}
        try:
            status = get_training_status_details(api, d_str)
        except Exception:
            status = {}

        entry = {
            "date": d_str,
            "resting_heart_rate": health.get("resting_heart_rate"),
            "hrv_last_night_avg_ms": deep_get(health, ["hrv.last_night_avg_ms"]),
            "hrv_seven_day_avg_ms": deep_get(health, ["hrv.seven_day_avg_ms"]),
            "total_sleep_hours": health.get("total_sleep_hours"),
            "sleep_score": health.get("sleep_score"),
            "vo2_max": deep_get(status, ["vo2_max.value"]),
            "training_status": status.get("status"),
            "acute_load": deep_get(status, ["training_load.acute_load"]),
            "chronic_load": deep_get(status, ["training_load.chronic_load"]),
            "acwr": deep_get(status, ["training_load.acwr"]),
            "acwr_status": deep_get(status, ["training_load.acwr_status"]),
        }
        trend.append({k: v for k, v in entry.items() if v is not None})

    return trend

def get_body_battery_trend(api, target_date, days=7):
    """Fetch daily Body Battery high/low and charged/drained values over the
    trailing `days` days -- a proxy for how well you're actually recovering
    day to day, complementary to HRV/RHR."""
    start_date = target_date - timedelta(days=days - 1)
    try:
        bb_data = api.get_body_battery(start_date.isoformat(), target_date.isoformat())
    except Exception as e:
        print(f"[body_battery] Warning: could not fetch body battery trend: {e}", file=sys.stderr)
        return []

    trend = []
    if isinstance(bb_data, list):
        for day_entry in bb_data:
            if not isinstance(day_entry, dict):
                continue
            cal_date = day_entry.get("date") or day_entry.get("calendarDate")
            charged = safe_int(day_entry.get("charged"))
            drained = safe_int(day_entry.get("drained"))

            values = day_entry.get("bodyBatteryValuesArray") or []
            levels = [
                v[1] for v in values
                if isinstance(v, (list, tuple)) and len(v) > 1 and v[1] is not None
            ]

            entry = {
                "date": cal_date,
                "charged": charged,
                "drained": drained,
                "high": max(levels) if levels else None,
                "low": min(levels) if levels else None
            }
            trend.append({k: v for k, v in entry.items() if v is not None})

    return trend

def get_activity_splits(api, activity_id, activity_type="run"):
    """Fetch and format activity splits lap list aligned with Garmin Connect export headers."""
    try:
        splits = api.get_activity_splits(activity_id)
    except Exception:
        splits = {}

    lap_dtos_raw = splits.get("lapDTOs", []) if isinstance(splits, dict) else []
    lap_dtos = []
    cumulative_sec = 0.0

    for lap in lap_dtos_raw:
        lap_distance_m = lap.get("distance", 0) or 0
        lap_duration_sec = lap.get("duration", 0) or lap.get("elapsedDuration", 0) or 0
        cumulative_sec += lap_duration_sec

        distance_km = round(lap_distance_m / 1000.0, 3) if lap_distance_m else 0.0
        time_min = round(lap_duration_sec / 60.0, 2) if lap_duration_sec else 0.0
        cumulative_time_min = round(cumulative_sec / 60.0, 2)

        lap_pace = format_pace(lap_distance_m, lap_duration_sec, activity_type)

        max_speed = lap.get("maxSpeed") or lap.get("maximumSpeed")
        best_pace = None
        if max_speed and max_speed > 0:
            best_sec_per_km = (1000.0 / float(max_speed))
            b_mins = int(best_sec_per_km // 60)
            b_secs = int(round(best_sec_per_km % 60))
            best_pace = f"{b_mins}:{b_secs:02d}"

        moving_duration_sec = lap.get("movingDuration") or lap_duration_sec
        moving_time_min = round(moving_duration_sec / 60.0, 2) if moving_duration_sec else None
        avg_moving_pace = format_pace(lap_distance_m, moving_duration_sec, activity_type)

        raw_stride = safe_float(lap.get("strideLength") or lap.get("avgStrideLength"))
        avg_stride_length_m = None
        if raw_stride is not None:
            avg_stride_length_m = round(raw_stride / 100.0, 4) if raw_stride > 3 else round(raw_stride, 4)

        raw_vo = safe_float(lap.get("verticalOscillation") or lap.get("avgVerticalOscillation"))
        vertical_oscillation_cm = None
        if raw_vo is not None:
            vertical_oscillation_cm = round(raw_vo / 10.0, 2) if raw_vo > 20 else round(raw_vo, 2)

        lap_obj = {
            "lap": safe_int(lap.get("lapIndex") or lap.get("splitIndex") or lap.get("lap")),
            "distance_km": distance_km,
            "time_min": time_min,
            "cumulative_time_min": cumulative_time_min,
            "moving_time_min": moving_time_min,
            "avg_pace": lap_pace,
            "avg_moving_pace": avg_moving_pace,
            "best_pace": best_pace,
            "avg_hr": safe_int(lap.get("averageHR") or lap.get("avgHR")),
            "max_hr": safe_int(lap.get("maxHR") or lap.get("maximumHR")),
            "calories": safe_int(lap.get("calories")),
            "avg_power_w": safe_int(lap.get("averagePower") or lap.get("avgPower") or lap.get("power")),
            "normalized_power_w": safe_int(lap.get("normalizedPower") or lap.get("normPower") or lap.get("averagePower") or lap.get("avgPower")),
            "cadence_spm": safe_int(lap.get("averageRunCadence") or lap.get("avgRunCadence") or lap.get("cadence") or lap.get("avgCadence")),
            "max_cadence_spm": safe_int(lap.get("maxRunCadence") or lap.get("maximumRunCadence") or lap.get("maxCadence")),
            "avg_gct_ms": safe_float(lap.get("groundContactTime") or lap.get("avgGroundContactTime") or lap.get("gct"), 1),
            "avg_stride_length_m": avg_stride_length_m,
            "vertical_oscillation_cm": vertical_oscillation_cm,
            "vertical_ratio_pct": safe_float(lap.get("verticalRatio") or lap.get("avgVerticalRatio") or lap.get("vertRatio"), 2),
            "elevation_gain_m": safe_float(lap.get("elevationGain") or lap.get("sumElevationGain") or lap.get("ascent"), 1),
            "elevation_loss_m": safe_float(lap.get("elevationLoss") or lap.get("sumElevationLoss") or lap.get("descent"), 1),
            "intensityType": lap.get("intensityType") or lap.get("stepType")
        }
        lap_dtos.append({k: v for k, v in lap_obj.items() if v is not None})
    return lap_dtos

# ---------------------------------------------------------------------------
# Multisport (triathlon/duathlon) support
#
# Garmin stores a multisport session as ONE parent activity (activityType
# typeKey == "multi_sport") plus a separate CHILD activity for every leg
# (Swim, Transition 1, Bike, Transition 2, Run), each with its own
# activityId. Calling get_activity_splits() on the *parent* id (what the
# original script did implicitly, since it treated the parent like any
# other activity) returns Garmin's internal lapDTOs for the whole session,
# which is why each leg showed up as a flat "lap" instead of its own
# activity with its own splits.
#
# The fix: detect multi_sport parents, resolve their child activity ids via
# api.get_activity(parent_id) -> metadataDTO.childIds (the documented shape
# for this on Garmin Connect), then treat every child id exactly like a
# normal activity: pull its own summary + its own real splits.
# ---------------------------------------------------------------------------

def is_multisport_type(act_type):
    t = (act_type or "").lower()
    return "multi_sport" in t or "multisport" in t

def _find_id_like_lists(obj, path=""):
    """Debug helper: walk a dict/list looking for keys that smell like child-id
    lists, so we can report candidates to stderr if our primary lookup fails."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            if "child" in k.lower():
                found.append((new_path, v))
            found.extend(_find_id_like_lists(v, new_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):  # sample only, avoid huge dumps
            found.extend(_find_id_like_lists(item, f"{path}[{i}]"))
    return found

def get_child_activity_ids(api, parent_activity_id):
    """Return the list of child activity IDs (one per leg) for a multi_sport
    parent activity. Returns [] if none could be resolved, and prints a
    debug dump to stderr in that case so the lookup can be corrected."""
    try:
        detail = api.get_activity(parent_activity_id)
    except Exception as e:
        print(f"[multisport] Warning: could not fetch activity detail for parent {parent_activity_id}: {e}", file=sys.stderr)
        return []

    if not isinstance(detail, dict):
        return []

    metadata = detail.get("metadataDTO", {}) if isinstance(detail.get("metadataDTO"), dict) else {}

    child_ids = (
        metadata.get("childIds")
        or metadata.get("childActivityIds")
        or detail.get("childIds")
        or detail.get("childActivityIds")
        or []
    )

    if isinstance(child_ids, dict):
        child_ids = list(child_ids.values())
    child_ids = [c for c in (child_ids or []) if c]

    if not child_ids:
        candidates = _find_id_like_lists(detail)
        print(
            f"[multisport] Warning: no child activity ids found for parent {parent_activity_id} "
            f"via metadataDTO.childIds. Candidate 'child*' keys found in response: "
            f"{candidates if candidates else 'none'}. Falling back to treating the parent "
            f"as a single activity (legs will appear as laps, not activities).",
            file=sys.stderr
        )

    return child_ids

def get_child_activity_summary(api, child_id):
    """Fetch a single leg (child) activity's summary info. The single-activity
    detail endpoint nests most numeric fields under summaryDTO, unlike the
    activity-list endpoint which has them at the top level, so we check both."""
    try:
        detail = api.get_activity(child_id)
    except Exception as e:
        print(f"[multisport] Warning: could not fetch child activity {child_id}: {e}", file=sys.stderr)
        detail = {}

    if not isinstance(detail, dict):
        detail = {}

    summary = detail.get("summaryDTO", {}) if isinstance(detail.get("summaryDTO"), dict) else {}

    act_type = deep_get(
        detail,
        ["activityTypeDTO.typeKey", "activityType.typeKey", "activityType"],
        ""
    )
    name = detail.get("activityName") or act_type or "Leg"

    distance_m = summary.get("distance") or detail.get("distance") or 0
    duration_sec = summary.get("duration") or detail.get("duration") or 0

    avg_hr = summary.get("averageHR") or detail.get("averageHR")
    max_hr = summary.get("maxHR") or detail.get("maxHR")
    aerobic_te = summary.get("trainingEffect") or summary.get("aerobicTrainingEffect") or detail.get("aerobicTrainingEffect")
    anaerobic_te = summary.get("anaerobicTrainingEffect") or detail.get("anaerobicTrainingEffect")

    return {
        "activityId": child_id,
        "name": name,
        "type": act_type,
        "distance_km": round(distance_m / 1000.0, 2) if distance_m else 0.0,
        "duration_mins": round(duration_sec / 60.0, 2) if duration_sec else 0.0,
        "avg_pace": format_pace(distance_m, duration_sec, act_type),
        "average_hr": safe_float(avg_hr),
        "max_hr": safe_float(max_hr),
        "aerobic_training_effect": safe_float(aerobic_te),
        "anaerobic_training_effect": safe_float(anaerobic_te),
    }

def expand_multisport_activity(api, parent_act):
    """Given a multi_sport parent activity dict (from get_activities_by_date),
    return a list of per-leg activity objects (Swim/T1/Bike/T2/Run), each with
    its own nested activity_splits. Returns [] if legs couldn't be resolved,
    signalling the caller should fall back to default single-activity handling."""
    parent_id = parent_act.get("activityId")
    child_ids = get_child_activity_ids(api, parent_id)
    if not child_ids:
        return []

    transition_count = 0
    legs = []
    for child_id in child_ids:
        child_obj = get_child_activity_summary(api, child_id)

        if "transition" in (child_obj.get("type") or "").lower():
            transition_count += 1
            child_obj["name"] = f"Transition {transition_count} (T{transition_count})"

        child_splits = get_activity_splits(api, child_id, child_obj.get("type"))
        if child_splits:
            child_obj["activity_splits"] = child_splits

        child_obj["parentActivityId"] = parent_id
        legs.append({k: v for k, v in child_obj.items() if v is not None})

    return legs

def get_activities(api, target_date_str):
    """Fetch activities, calculate avg_pace, and nest their splits directly below
    each activity. Multisport (triathlon/duathlon) parent activities are expanded
    into their individual legs (Swim, T1, Bike, T2, Run) instead of being returned
    as one activity with the legs flattened into laps."""
    try:
        activities = api.get_activities_by_date(target_date_str, target_date_str)
    except Exception:
        activities = []

    formatted_activities = []
    for act in activities:
        act_id = act.get("activityId")
        act_type = deep_get(act, ["activityType.typeKey", "activityType"], "")

        if is_multisport_type(act_type) and act_id:
            legs = expand_multisport_activity(api, act)
            if legs:
                formatted_activities.extend(legs)
                continue

        distance_m = act.get("distance", 0) or 0
        distance_km = round(distance_m / 1000.0, 2) if distance_m else 0.0
        duration_sec = act.get("duration", 0) or 0
        duration_mins = round(duration_sec / 60.0, 2) if duration_sec else 0.0

        activity_pace = format_pace(distance_m, duration_sec, act_type)

        activity_obj = {
            "activityId": act_id,
            "name": act.get("activityName"),
            "type": act_type,
            "distance_km": distance_km,
            "duration_mins": duration_mins,
            "avg_pace": activity_pace,
            "average_hr": safe_float(act.get("averageHR") or act.get("avgHR")),
            "max_hr": safe_float(act.get("maxHR") or act.get("maximumHR")),
            "aerobic_training_effect": safe_float(act.get("aerobicTrainingEffect")),
            "anaerobic_training_effect": safe_float(act.get("anaerobicTrainingEffect"))
        }

        if act_id:
            splits = get_activity_splits(api, act_id, act_type)
            if splits:
                activity_obj["activity_splits"] = splits

        formatted_activities.append({k: v for k, v in activity_obj.items() if v is not None})
    return formatted_activities

def strip_volatile_fields(payload):
    """Return a copy of payload with fields that intentionally change on every
    run but don't reflect any real new data (e.g. the run timestamp) removed,
    so two payloads can be compared for MEANINGFUL change."""
    stripped = dict(payload)
    stripped.pop("generated_at_local", None)
    return stripped

def main():
    ph_today = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description="Fetch Garmin data with Garmin export-aligned lap splits.")
    parser.add_argument("--date", type=str, default=ph_today, help="Date in YYYY-MM-DD format")
    parser.add_argument("--trend-days", type=int, default=7,
                         help="Number of trailing days for the DAILY trend series "
                              "(RHR/HRV/sleep -- noisy metrics that need daily resolution). "
                              "Set to 0 to skip.")
    parser.add_argument("--trend-weeks", type=int, default=12,
                         help="Number of trailing weeks for the WEEKLY-sampled long-range trend "
                              "(VO2max/chronic load -- slow-moving metrics, weekly resolution is "
                              "sufficient and far cheaper on API calls). Set to 0 to skip.")
    parser.add_argument("--body-battery-days", type=int, default=7,
                         help="Number of trailing days to include in the Body Battery trend. "
                              "Set to 0 to skip.")
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

    training_history = get_training_history(api, target_date)
    health_stats = get_health_stats(api, target_date_str)
    training_status = get_training_status_details(api, target_date_str)
    activities = get_activities(api, target_date_str)

    payload = {
        "date": target_date_str,
        "generated_at_local": datetime.now(ZoneInfo("Asia/Manila")).isoformat(timespec="minutes"),
        "training_history": training_history,
        "health_stats": health_stats,
        "training_status": training_status,
        "activities": activities
    }

    if args.trend_days > 0:
        payload["trend_recent_daily"] = get_metric_trend(api, target_date, days=args.trend_days, interval=1)

    if args.trend_weeks > 0:
        payload["trend_long_range_weekly"] = get_metric_trend(
            api, target_date, days=args.trend_weeks * 7, interval=7
        )

    if args.body_battery_days > 0:
        payload["body_battery_trend"] = get_body_battery_trend(api, target_date, days=args.body_battery_days)

    os.makedirs("data", exist_ok=True)
    file_path = os.path.join("data", f"garmin_{target_date_str}.json")

    existing_payload = None
    if os.path.exists(file_path):
        try:
            with open(file_path) as f:
                existing_payload = json.load(f)
        except Exception:
            existing_payload = None  # corrupt/partial file from a prior run -- just overwrite it

    if existing_payload is not None and strip_volatile_fields(existing_payload) == strip_volatile_fields(payload):
        print(
            f"No meaningful change since last run (only generated_at_local would differ) -- "
            f"skipping write to keep git history clean: {file_path}"
        )
    else:
        with open(file_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"Successfully generated Garmin JSON at: {file_path}")

if __name__ == "__main__":
    main()
import os
import json
import argparse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from garminconnect import Garmin
from garmin_helpers import (
    get_training_status_details,
    get_body_battery_trend,
    get_activities,
)
from sport_trends import get_metric_trend


LOCAL_TZ = ZoneInfo("Asia/Manila")


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


def format_pace(distance_m, duration_sec, activity_type="run"):
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
    return f"{total_sec // 60}:{total_sec % 60:02d}"


def _history_sport(act):
    raw = deep_get(act, ["activityType.typeKey", "activityType", "sport", "sportType", "type"], "") or ""
    raw = str(raw).lower()
    if "run" in raw or "jog" in raw:
        return "running"
    if any(x in raw for x in ("cycl", "bike", "biking")):
        return "cycling"
    if "swim" in raw:
        return "swimming"
    if any(x in raw for x in ("multi", "triathlon", "duathlon", "aquathlon")):
        return "multisport"
    if "transition" in raw:
        return "transition"
    return "other"


def _history_date(act, fallback):
    value = act.get("startTimeLocal") or act.get("startTimeGMT") or act.get("startTime") or ""
    if isinstance(value, str) and len(value) >= 10:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return fallback


def _history_distance_km(act):
    if act.get("distance_km") is not None:
        return float(act.get("distance_km") or 0)
    return float(act.get("distance") or 0) / 1000.0


def _history_duration_hours(act):
    if act.get("duration_mins") is not None:
        return float(act.get("duration_mins") or 0) / 60.0
    duration = act.get("duration") or act.get("elapsedDuration") or act.get("movingDuration") or 0
    return float(duration or 0) / 3600.0


def _history_load(act):
    value = deep_get(act, [
        "exerciseLoad", "trainingLoad", "activityTrainingLoad",
        "activityTrainingLoadDTO.trainingLoad", "summaryDTO.trainingLoad",
        "summaryDTO.exerciseLoad", "activityTrainingLoadDTO.exerciseLoad"
    ])
    return safe_float(value, 1)


def _history_empty():
    return {"activity_count": 0, "distance_km": 0.0, "duration_hours": 0.0, "exercise_load": 0.0, "exercise_load_available": False}


def _history_add(bucket, act):
    bucket["activity_count"] += 1
    bucket["distance_km"] += _history_distance_km(act)
    bucket["duration_hours"] += _history_duration_hours(act)
    load = _history_load(act)
    if load is not None:
        bucket["exercise_load"] += load
        bucket["exercise_load_available"] = True


def _history_finalize(bucket):
    out = {"activity_count": bucket["activity_count"], "distance_km": round(bucket["distance_km"], 2), "duration_hours": round(bucket["duration_hours"], 2)}
    if bucket.get("exercise_load_available"):
        out["exercise_load"] = round(bucket["exercise_load"], 1)
    return out


def _history_expand_multisport(api, activities):
    expanded = []
    for act in activities or []:
        if _history_sport(act) != "multisport" or not act.get("activityId"):
            expanded.append(act)
            continue
        try:
            detail = api.get_activity(act["activityId"])
            meta = detail.get("metadataDTO", {}) if isinstance(detail, dict) else {}
            child_ids = meta.get("childIds") or meta.get("childActivityIds") or detail.get("childIds") or detail.get("childActivityIds") or []
            if isinstance(child_ids, dict):
                child_ids = list(child_ids.values())
        except Exception:
            child_ids = []
        if not child_ids:
            expanded.append(act)
            continue
        for child_id in child_ids:
            try:
                detail = api.get_activity(child_id)
            except Exception:
                continue
            summary = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
            typ = deep_get(detail, ["activityTypeDTO.typeKey", "activityType.typeKey", "activityType"], "") or ""
            expanded.append({
                "activityId": child_id,
                "activityType": {"typeKey": typ},
                "distance": summary.get("distance") or detail.get("distance") or 0,
                "duration": summary.get("duration") or detail.get("duration") or 0,
                "exerciseLoad": deep_get(summary, ["trainingLoad", "exerciseLoad"]) or deep_get(detail, ["trainingLoad", "exerciseLoad", "activityTrainingLoad"]),
            })
    return expanded


def get_training_history(api, target_date):
    start_history_date = target_date - timedelta(days=27)
    try:
        historical_activities = api.get_activities_by_date(start_history_date.isoformat(), target_date.isoformat())
    except Exception:
        historical_activities = []
    historical_activities = _history_expand_multisport(api, historical_activities)
    by_date = {}
    for act in historical_activities:
        d = _history_date(act, target_date)
        by_date.setdefault(d, []).append(act)
    sports = ("running", "cycling", "swimming", "multisport", "other", "transition")

    def window(start_date, end_date):
        buckets = {s: _history_empty() for s in sports}
        for d, acts in by_date.items():
            if start_date <= d <= end_date:
                for act in acts:
                    _history_add(buckets[_history_sport(act)], act)
        total = _history_empty()
        for bucket in buckets.values():
            total["activity_count"] += bucket["activity_count"]
            total["distance_km"] += bucket["distance_km"]
            total["duration_hours"] += bucket["duration_hours"]
            if bucket.get("exercise_load_available"):
                total["exercise_load"] += bucket["exercise_load"]
                total["exercise_load_available"] = True
        return buckets, total

    seven_start = target_date - timedelta(days=6)
    seven_sport, seven_total = window(seven_start, target_date)
    weekly = []
    for i in range(4):
        week_end = target_date - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=6)
        buckets, total = window(week_start, week_end)
        weekly.append({
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "total_endurance": _history_finalize(total),
            "sports": {s: _history_finalize(buckets[s]) for s in sports if buckets[s]["activity_count"] > 0}
        })
    weekly.reverse()
    sport_7 = {s: _history_finalize(seven_sport[s]) for s in sports if seven_sport[s]["activity_count"] > 0}
    total_7 = _history_finalize(seven_total)
    running_weekly = [w["sports"].get("running", {}).get("distance_km", 0.0) for w in weekly]
    running_avg = round(sum(running_weekly) / len(running_weekly), 1) if running_weekly else 0.0
    return {
        "7_day": {"total_endurance": total_7, "sports": sport_7},
        "28_day": {"avg_weekly_running_distance_km": running_avg, "weekly_total_endurance": weekly},
        "legacy_running_summary": {
            "7d_distance_km": sport_7.get("running", {}).get("distance_km", 0.0),
            "28d_avg_weekly_distance_km": running_avg,
            "weekly_distance_last_4_weeks_km": running_weekly
        }
    }


def _epoch_to_local(value):
    """Convert Garmin epoch seconds/milliseconds to an Asia/Manila ISO timestamp."""
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, tz=timezone.utc).astimezone(LOCAL_TZ)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def _garmin_timestamp_to_local(value):
    """Parse Garmin event timestamps, handling epoch and ISO/string forms."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return _epoch_to_local(value)
    text = str(value).strip()
    try:
        return _epoch_to_local(text)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(LOCAL_TZ)
    except ValueError:
        return None


def _nap_event_start(event):
    return deep_get(event, [
        "eventStartTimeGmt", "eventStartTimeGMT", "eventStartTime", "startTimeGMT",
        "startTimeGmt", "startTime", "EventStartTimeInSeconds"
    ])


def _nap_event_duration_seconds(event):
    value = deep_get(event, [
        "durationInMilliseconds", "durationMilliseconds", "durationMs", "duration", "Duration"
    ])
    if value is None:
        return None
    try:
        numeric = float(value)
        # Garmin body-battery events use milliseconds; exported event data may use seconds.
        return numeric / 1000.0 if numeric > 10000 else numeric
    except (ValueError, TypeError):
        return None


def get_previous_day_nap(api, target_date):
    """Return the most recent nap ending before today's morning, using actual event timestamps."""
    nap_date = target_date - timedelta(days=1)
    try:
        events = api.get_body_battery_events(nap_date.isoformat()) or []
    except Exception:
        events = []

    if isinstance(events, dict):
        events = events.get("bodyBatteryActivityEvent") or events.get("bodyBatteryActivityEvents") or events.get("events") or []
    if not isinstance(events, list):
        return None

    candidates = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(deep_get(event, ["eventType", "EventType", "type"], "")).upper()
        if event_type != "NAP":
            continue
        start = _garmin_timestamp_to_local(_nap_event_start(event))
        duration_seconds = _nap_event_duration_seconds(event)
        if start is None or duration_seconds is None or duration_seconds <= 0:
            continue
        end = start + timedelta(seconds=duration_seconds)
        if start.date() == nap_date or end.date() == nap_date:
            candidates.append((start, end))

    if not candidates:
        return None

    start, end = max(candidates, key=lambda item: item[1])
    duration_minutes = (end - start).total_seconds() / 60.0
    return {
        "date": start.date().isoformat(),
        "start_local": start.isoformat(timespec="seconds"),
        "end_local": end.isoformat(timespec="seconds"),
        "duration_minutes": round(duration_minutes, 1),
    }


def get_health_stats(api, target_date_str, target_date=None):
    """Fetch detailed daily health data and carry the previous day's actual nap into today's metrics."""
    stats = {}
    try:
        stats = api.get_stats(target_date_str) or {}
    except Exception:
        pass

    rhr = safe_int(stats.get("restingHeartRate") or stats.get("rhr"))
    total_steps = safe_int(stats.get("totalSteps") or stats.get("steps"))

    sleep_data = {}
    try:
        sleep_data = api.get_sleep_data(target_date_str) or {}
    except Exception:
        pass
    sleep_dto = sleep_data.get("dailySleepDTO", {}) if isinstance(sleep_data, dict) else {}
    sleep_scores = sleep_dto.get("sleepScores", {}) or {}
    overall_score = sleep_scores.get("overall", {}) or {}
    sleep_score = safe_int(overall_score.get("value") or sleep_dto.get("overallSleepScore") or sleep_dto.get("sleepScore"))
    sleep_seconds = sleep_dto.get("sleepTimeSeconds")

    def hours(seconds):
        return safe_float((seconds or 0) / 3600 if seconds is not None else None, 2)

    sleep_stages = {
        "deep": hours(sleep_dto.get("deepSleepSeconds")),
        "light": hours(sleep_dto.get("lightSleepSeconds")),
        "rem": hours(sleep_dto.get("remSleepSeconds")),
        "awake": hours(sleep_dto.get("awakeSleepSeconds")),
    }
    sleep_stages = {k: v for k, v in sleep_stages.items() if v is not None}

    hrv_data = {}
    try:
        hrv_data = api.get_hrv_data(target_date_str) or {}
    except Exception:
        pass
    hrv_summary = hrv_data.get("hrvSummary", {}) if isinstance(hrv_data, dict) else {}
    hrv_last_night = safe_float(hrv_summary.get("lastNightAvg") or hrv_summary.get("lastNight5MinHigh"), 1)
    hrv_weekly = safe_float(hrv_summary.get("weeklyAvg"), 1)
    hrv_status = hrv_summary.get("status")

    baseline = hrv_summary.get("baseline") or hrv_summary.get("baselineBalancedRange") or hrv_summary.get("baselineBalancedRangeDTO") or {}
    baseline_range = {
        "lowUpper": safe_float(baseline.get("lowUpper"), 2),
        "balancedLow": safe_float(baseline.get("balancedLow"), 2),
        "balancedUpper": safe_float(baseline.get("balancedUpper"), 2),
        "markerValue": baseline.get("markerValue"),
    }
    baseline_range = {k: v for k, v in baseline_range.items() if v is not None}

    hrv = {
        "last_night_avg_ms": hrv_last_night,
        "seven_day_avg_ms": hrv_weekly,
        "status": hrv_status,
    }
    if baseline_range:
        hrv["baseline_balanced_range"] = baseline_range
    hrv = {k: v for k, v in hrv.items() if v is not None}

    nap = get_previous_day_nap(api, target_date) if target_date else None
    nap_minutes = nap.get("duration_minutes") if nap else 0.0
    total_sleep_hours = hours(sleep_seconds)
    total_sleep_including_nap_hours = round(total_sleep_hours + (nap_minutes / 60.0), 2) if total_sleep_hours is not None else None

    result = {
        "resting_heart_rate": rhr,
        "hrv": hrv,
        "sleep_score": sleep_score,
        "total_sleep_hours": total_sleep_hours,
        "sleep_hours_including_previous_day_nap": total_sleep_including_nap_hours,
        "sleep_stages_hours": sleep_stages,
        "nap_minutes": safe_float(nap_minutes, 1),
        "previous_day_nap": nap,
        "total_steps": total_steps,
    }
    return {k: v for k, v in result.items() if v is not None}


def build_daily_readiness(health_stats, training_status):
    """Build the compact snapshot from the detailed structures already fetched."""
    ts = training_status or {}
    load = ts.get("training_load") or {}
    vo2 = ts.get("vo2_max") or {}
    return {
        "resting_hr_bpm": health_stats.get("resting_heart_rate"),
        "hrv_last_night_avg_ms": deep_get(health_stats, ["hrv.last_night_avg_ms"]),
        "hrv_7_day_avg_ms": deep_get(health_stats, ["hrv.seven_day_avg_ms"]),
        "hrv_status": deep_get(health_stats, ["hrv.status"]),
        "sleep_hours": health_stats.get("total_sleep_hours"),
        "sleep_hours_including_previous_day_nap": health_stats.get("sleep_hours_including_previous_day_nap"),
        "sleep_score": health_stats.get("sleep_score"),
        "nap_minutes": health_stats.get("nap_minutes"),
        "previous_day_nap": health_stats.get("previous_day_nap"),
        "training_status": ts.get("status"),
        "acute_load": load.get("acute_load"),
        "chronic_load": load.get("chronic_load"),
        "acwr": load.get("acwr"),
        "vo2_max": vo2.get("value"),
        "recovery_time_hours": ts.get("recovery_time_hours"),
    }


def strip_volatile_fields(payload):
    if not isinstance(payload, dict):
        return payload
    cleaned = dict(payload)
    cleaned.pop("generated_at_local", None)
    return cleaned


def migrate_legacy_data_files(data_dir="data"):
    """Move legacy flat YYYY-MM-DD.json files into data/YYYY/MM/ once."""
    if not os.path.isdir(data_dir):
        return
    for filename in os.listdir(data_dir):
        if not filename.endswith(".json") or filename == "latest.json":
            continue
        stem = filename[:-5]
        try:
            target_date = datetime.strptime(stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        source = os.path.join(data_dir, filename)
        month_dir = os.path.join(data_dir, f"{target_date.year:04d}", f"{target_date.month:02d}")
        destination = os.path.join(month_dir, filename)
        os.makedirs(month_dir, exist_ok=True)
        if not os.path.exists(destination):
            os.replace(source, destination)
        else:
            os.remove(source)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="date", default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--trend-days", type=int, default=7)
    parser.add_argument("--trend-weeks", type=int, default=12)
    parser.add_argument("--body-battery-days", type=int, default=7)
    args = parser.parse_args()

    data_dir = "data"
    tokenstore = os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect")
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now(LOCAL_TZ).date()
    api = Garmin()
    api.login(tokenstore=os.path.expanduser(tokenstore))

    health_stats = get_health_stats(api, target_date.isoformat(), target_date)
    training_status = get_training_status_details(api, target_date.isoformat())
    training_history = get_training_history(api, target_date)
    activities = get_activities(api, target_date)
    trends = get_metric_trend(api, target_date, days=args.trend_days, interval=1)
    weekly_trends = get_metric_trend(api, target_date, days=args.trend_weeks * 7, interval=7)
    body_battery_trend = get_body_battery_trend(api, target_date, days=args.body_battery_days)

    payload = {
        "date": target_date.isoformat(),
        "daily_readiness": build_daily_readiness(health_stats, training_status),
        "health_stats": health_stats,
        "training_status": training_status,
        "training_history": training_history,
        "trend_recent_daily": trends,
        "trend_long_range_weekly": weekly_trends,
        "body_battery_trend": body_battery_trend,
        "activities": activities,
    }
    payload = strip_volatile_fields(payload)

    os.makedirs(data_dir, exist_ok=True)
    latest_path = os.path.join(data_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(latest_path)


if __name__ == "__main__":
    main()

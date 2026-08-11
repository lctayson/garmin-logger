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

def main():
    # Force Philippine Time (UTC+8) so cron jobs running on UTC servers pick up the correct local date
    ph_today = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description="Fetch Garmin telemetry and health metrics matching strict schema.")
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
        "motivation_0_10": None
    }

    # 4. FETCH TARGET DATE ACTIVITIES & INTERVALS
    try:
        activities = api.get_activities_by_date(target_date_str, target_date_str)
    except Exception:
        activities = []

    activities_list = []
    for act in activities:
        act_id = act.get("activityId")
        act_type = deep_get(act, ["activityType.typeKey", "activityType"], "running").lower()
        is_running = "run" in act_type

        avg_speed_mps = act.get("averageSpeed", None)
        avg_pace_str, avg_pace_sec = speed_to_pace_metrics(avg_speed_mps)

        avg_gap_mps = deep_get(act, ["averageGradeAdjustedSpeed", "gradeAdjustedSpeed"], None)
        avg_gap_str, avg_gap_sec = speed_to_pace_metrics(avg_gap_mps) if avg_gap_mps else (None, None)

        raw_stride = deep_get(act, ["avgStrideLength", "averageStrideLength", "strideLength"], None)
        avg_stride_m = format_stride_length(raw_stride) if is_running else None

        summary = {
            "activity_id": act_id,
            "activity_type": act_type,
            "activity_name": deep_get(act, ["activityName"]),
            "start_time": deep_get(act, ["startTimeLocal"]),
            "total_distance_km": round(act.get("distance", 0) / 1000.0, 3) if act.get("distance") else None,
            "total_duration_min": round(act.get("duration", 0) / 60.0, 2) if act.get("duration") else None,
            "run_time_min": round(act.get("movingDuration", 0) / 60.0, 2) if is_running and act.get("movingDuration") else None,
            "walk_time_min": None,
            "idle_time_min": None,
            "avg_pace": avg_pace_str,
            "avg_pace_sec_per_km": avg_pace_sec,
            "avg_gap": avg_gap_str,
            "avg_gap_sec_per_km": avg_gap_sec,
            "avg_hr": safe_int(deep_get(act, ["averageHR", "avgHR"])),
            "max_hr": safe_int(deep_get(act, ["maxHR", "maximumHR"])),
            "avg_power_w": safe_int(deep_get(act, ["averagePower", "avgPower"])),
            "max_power_w": safe_int(deep_get(act, ["maxPower", "maximumPower"])),
            "normalized_power_w": safe_int(deep_get(act, ["normalizedPower", "normPower"])),
            "avg_cadence": safe_int(deep_get(act, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence"])) if is_running else None,
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
        if act_id:
            try:
                splits = api.get_activity_splits(act_id)
                lap_dtos = splits.get("lapDTOs", [])
                for idx, lap in enumerate(lap_dtos, start=1):
                    l_dist = round(lap.get("distance", 0) / 1000.0, 3) if lap.get("distance") else None
                    l_speed = lap.get("averageSpeed", None)
                    l_pace, l_pace_sec = speed_to_pace_metrics(l_speed)
                    
                    l_gap_speed = deep_get(lap, ["averageGradeAdjustedSpeed", "gradeAdjustedSpeed"], None)
                    l_gap_pace, l_gap_sec = speed_to_pace_metrics(l_gap_speed) if l_gap_speed else (None, None)

                    raw_lap_stride = deep_get(lap, ["avgStrideLength", "strideLength", "averageStrideLength"], None)
                    lap_stride_m = format_stride_length(raw_lap_stride) if is_running else None

                    intervals.append({
                        "interval_number": idx,
                        "step_type": deep_get(lap, ["stepType"], "Run"),
                        "time_min": round(lap.get("duration", 0) / 60.0, 2) if lap.get("duration") else None,
                        "distance_km": l_dist,
                        "avg_pace": l_pace,
                        "avg_pace_sec_per_km": l_pace_sec,
                        "avg_gap": l_gap_pace,
                        "avg_gap_sec_per_km": l_gap_sec,
                        "avg_hr": safe_int(deep_get(lap, ["averageHR", "avgHR"])),
                        "max_hr": safe_int(deep_get(lap, ["maxHR", "maximumHR"])),
                        "power_w": safe_int(deep_get(lap, ["averagePower", "avgPower", "power"])),
                        "max_power_w": safe_int(deep_get(lap, ["maxPower", "maximumPower"])),
                        "cadence": safe_int(deep_get(lap, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence"])) if is_running else None,
                        "avg_gct_ms": safe_int(deep_get(lap, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"])) if is_running else None,
                        "avg_stride_length_m": lap_stride_m,
                        "vertical_oscillation_cm": safe_float(deep_get(lap, ["verticalOscillation", "avgVerticalOscillation"])) if is_running else None,
                        "vertical_ratio_pct": safe_float(deep_get(lap, ["verticalRatio", "avgVerticalRatio"])) if is_running else None,
                        "elevation_gain_m": safe_float(deep_get(lap, ["elevationGain", "totalAscent"])),
                        "elevation_loss_m": safe_float(deep_get(lap, ["elevationLoss", "totalDescent"])),
                        "avg_temperature_c": safe_float(deep_get(lap, ["averageTemperature", "temperature"]))
                    })
            except Exception:
                pass

        activities_list.append({
            "summary": summary,
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
    print(f"Successfully generated strict-schema JSON for {target_date_str} at: {file_path}")

if __name__ == "__main__":
    main()

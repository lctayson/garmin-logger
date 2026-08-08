import json
from datetime import datetime

def build_multi_activity_payload(garmin_activities, garmin_health_data):
    """
    Combines multi-sport activity data with comprehensive health, sleep stages, 
    and HRV metrics into a structured JSON payload.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    activities_list = []
    
    for act in garmin_activities:
        # 1. High-Level Activity Summary
        summary = {
            "activity_type": act.get('activityType', {}).get('typeKey', 'unknown'),
            "start_time": act.get('startTimeLocal', 'N/A'),
            "total_distance_km": round(act.get('distance', 0) / 1000, 3),
            "total_duration_min": round(act.get('duration', 0) / 60, 2),
            "avg_pace": act.get('avgPace', 'N/A'),
            "avg_hr": act.get('averageHR', 'N/A'),
            "max_hr": act.get('maxHR', 'N/A'),
            "avg_cadence": act.get('averageRunCadence', act.get('averageCadence', 'N/A')),
            "avg_gct_ms": act.get('avgGroundContactTime', 'N/A'),
            "avg_stride_length_m": act.get('avgStrideLength', 'N/A'),
            "avg_vertical_oscillation_cm": act.get('avgVerticalOscillation', 'N/A'),
            "aerobic_te": act.get('aerobicTrainingEffect', 'N/A')
        }
        
        # 2. Granular Intervals/Laps
        intervals = []
        for idx, lap in enumerate(act.get('laps', []), start=1):
            intervals.append({
                "interval_number": idx,
                "step_type": lap.get("stepType", "Unknown"),
                "time_min": round(lap.get("duration", 0) / 60, 2),
                "distance_km": round(lap.get("distance", 0) / 1000, 3),
                "avg_pace": lap.get("avgPace", 'N/A'),
                "avg_hr": lap.get("averageHR", 'N/A'),
                "max_hr": lap.get("maxHR", 'N/A'),
                "cadence": lap.get("averageRunCadence", lap.get("averageCadence", 'N/A')),
                "avg_gct_ms": lap.get("groundContactTime", 'N/A'),
                "avg_stride_length_m": lap.get("strideLength", 'N/A'),
                "vertical_oscillation_cm": lap.get("verticalOscillation", 'N/A'),
                "power_w": lap.get("averagePower", 'N/A')
            })
            
        activities_list.append({
            "summary": summary,
            "intervals": intervals
        })
        
    # 3. Enhanced Daily Health, Sleep Stages & HRV Metrics
    # Note: Garmin Connect API returns sleep stage durations typically in seconds.
    sleep_data = garmin_health_data.get('sleepMetrics', {})
    
    health_metrics = {
        "resting_hr": garmin_health_data.get('restingHR', 'N/A'),
        "sleep_score": garmin_health_data.get('sleepScore', 'N/A'),
        "total_sleep_hours": round(garmin_health_data.get('sleepDuration', 0) / 3600, 2),
        "sleep_stages_hours": {
            "deep": round(sleep_data.get('deepSleepSeconds', 0) / 3600, 2),
            "light": round(sleep_data.get('lightSleepSeconds', 0) / 3600, 2),
            "rem": round(sleep_data.get('remSleepSeconds', 0) / 3600, 2),
            "awake": round(sleep_data.get('awakeSleepSeconds', 0) / 3600, 2)
        },
        "hrv": {
            "last_night_avg_ms": garmin_health_data.get('lastNightAvgHRV', 'N/A'),
            "status": garmin_health_data.get('hrvStatus', 'N/A'),
            "baseline_balanced_range": garmin_health_data.get('hrvBaseline', 'N/A')
        },
        "readiness_score": garmin_health_data.get('readinessScore', 'N/A')
    }
    
    return {
        "date": today,
        "health_metrics": health_metrics,
        "activities": activities_list
    }

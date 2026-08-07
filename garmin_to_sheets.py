import os
import json
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from garminconnect import Garmin

# --- CONFIGURATION ---
SPREADSHEET_NAME = "Garmin_Metrics_Log"

google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
garmin_tokens_json = os.environ.get("GARMIN_TOKENS_JSON")

if not google_creds_json:
    raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable is missing.")
if not garmin_tokens_json:
    raise ValueError("GARMIN_TOKENS_JSON environment variable is missing.")

CREDENTIALS_DICT = json.loads(google_creds_json)

def ensure_worksheet_with_headers(sh, title, headers):
    try:
        worksheet = sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=title, rows="500", cols=len(headers) + 2)
    
    existing_rows = worksheet.get_all_values()
    if not existing_rows or existing_rows[0] != headers:
        worksheet.insert_row(headers, 1)
    return worksheet

def format_time(seconds):
    if not seconds or seconds == "N/A" or seconds <= 0:
        return "N/A"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"

def speed_to_pace_metrics(speed_mps):
    if not speed_mps or speed_mps <= 0:
        return "N/A", "N/A"
    sec_per_km = 1000.0 / speed_mps
    formatted_pace = format_time(sec_per_km)
    decimal_pace = round(sec_per_km / 60.0, 2)
    return formatted_pace, decimal_pace

def get_lap_metric(lap, possible_keys, default="N/A"):
    """Safely checks multiple alternative keys for a Garmin lap metric."""
    for key in possible_keys:
        val = lap.get(key)
        if val is not None and val != "":
            return val
    return default

def main():
    token_dir = "./.garminconnect"
    os.makedirs(token_dir, exist_ok=True)
    with open(os.path.join(token_dir, "garmin_tokens.json"), "w") as f:
        f.write(garmin_tokens_json)

    api = Garmin()
    api.login(token_dir)
    today = datetime.today().strftime("%Y-%m-%d")

    # 1. FETCH HEALTH METRICS
    stats = api.get_stats(today)
    rhr = stats.get("restingHeartRate", "N/A")
    total_steps = stats.get("totalSteps", "N/A")
    
    sleep_data = api.get_sleep_data(today).get("dailySleepDTO", {})
    sleep_score = sleep_data.get("sleepScores", {}).get("overall", {}).get("value", "N/A")
    sleep_hours = round(sleep_data.get("sleepTimeSeconds", 0) / 3600, 2)
    deep_hours = round(sleep_data.get("deepSleepSeconds", 0) / 3600, 2)
    light_hours = round(sleep_data.get("lightSleepSeconds", 0) / 3600, 2)
    rem_hours = round(sleep_data.get("remSleepSeconds", 0) / 3600, 2)
    awake_hours = round(sleep_data.get("awakeSleepSeconds", 0) / 3600, 2)

    try:
        hrv_summary = api.get_hrv_data(today).get("hrvSummary", {})
        hrv_status, hrv_weekly, hrv_last = hrv_summary.get("status", "N/A"), hrv_summary.get("weeklyAvg", "N/A"), hrv_summary.get("lastNightAvg", "N/A")
    except:
        hrv_status, hrv_weekly, hrv_last = "N/A", "N/A", "N/A"

    # 2. FETCH ACTIVITY
    activities = api.get_activities(0, 1)
    latest = activities[0] if activities else {}
    avg_speed_mps = latest.get("averageSpeed", 0)
    recovery_threshold = avg_speed_mps * 0.8 

    laps_to_log = []
    if latest.get("activityId"):
        splits = api.get_activity_splits(latest.get("activityId"))
        interval_counter = 0
        for idx, lap in enumerate(splits.get("lapDTOs", [])):
            lap_idx = idx + 1
            l_dist = round(lap.get("distance", 0) / 1000, 2)
            l_speed = lap.get("averageSpeed", 0)
            
            meta = f"{lap.get('intensity', '')} {lap.get('stepType', '')} {lap.get('lapType', '')}".upper()
            
            if lap_idx == 1 and (l_dist > 0.5 or "WARM" in meta):
                step_type, int_idx = "Warm Up", "--"
            elif any(k in meta for k in ["REST", "RECOVERY"]) or (0 < l_speed < recovery_threshold):
                step_type, int_idx = "Recovery", interval_counter
            elif any(k in meta for k in ["COOL", "COOLDOWN"]):
                step_type, int_idx = "Cool Down", "--"
            else:
                interval_counter += 1
                step_type, int_idx = "Run", interval_counter

            l_pace, l_pace_dec = speed_to_pace_metrics(l_speed)
            
            # Expanded and corrected key mapping for Garmin split metrics
            cadence = get_lap_metric(lap, ["averageRunCadence", "avgRunCadence", "averageCadence", "runCadence", "cadence"])
            gct = get_lap_metric(lap, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"])
            stride = get_lap_metric(lap, ["avgStrideLength", "averageStrideLength", "strideLength"])
            vert_osc = get_lap_metric(lap, ["avgVerticalOscillation", "averageVerticalOscillation", "verticalOscillation"])
            vert_ratio = get_lap_metric(lap, ["avgVerticalRatio", "averageVerticalRatio", "verticalRatio"])
            power = get_lap_metric(lap, ["avgPower", "averagePower", "power"])
            max_power = get_lap_metric(lap, ["maxPower", "maximumPower"])

            laps_to_log.append([
                today, int_idx, step_type, lap_idx, format_time(lap.get("duration")), l_dist,
                l_pace, l_pace_dec, lap.get("averageHR", "N/A"), lap.get("maxHR", "N/A"), 
                cadence, gct, stride, vert_osc, vert_ratio, power, max_power, lap.get("calories", "N/A")
            ])

    # 3. WRITE TO SHEETS
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    client = gspread.authorize(ServiceAccountCredentials.from_json_keyfile_dict(CREDENTIALS_DICT, scope))
    sh = client.open(SPREADSHEET_NAME)

    ensure_worksheet_with_headers(sh, "Daily_Readiness", ["Date", "Readiness", "HRV Status", "HRV Weekly Avg", "HRV Last Night Avg", "Resting HR", "Sleep Score", "Total Sleep", "Deep", "Light", "REM", "Awake", "Steps"]).append_row(
        [today, "N/A", hrv_status, hrv_weekly, hrv_last, rhr, sleep_score, sleep_hours, deep_hours, light_hours, rem_hours, awake_hours, total_steps]
    )
    
    granularity = ensure_worksheet_with_headers(sh, "Workout_Granularity", ["Date", "Interval #", "Step Type", "Lap", "Time", "Dist (km)", "Avg Pace", "Avg Pace (dec)", "Avg HR", "Max HR", "Cadence", "GCT (ms)", "Stride (m)", "Vert Osc (cm)", "Vert Ratio (%)", "Power (W)", "Max Power (W)", "Calories"])
    for row in laps_to_log: granularity.append_row(row)

if __name__ == "__main__":
    main()

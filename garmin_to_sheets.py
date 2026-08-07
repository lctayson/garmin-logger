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

def main():
    print("Setting up Garmin token session...")
    token_dir = "./.garminconnect"
    os.makedirs(token_dir, exist_ok=True)
    token_file_path = os.path.join(token_dir, "garmin_tokens.json")
    
    with open(token_file_path, "w") as f:
        f.write(garmin_tokens_json)

    print("Connecting to Garmin Connect using pre-authenticated tokens...")
    api = Garmin()
    api.login(token_dir)

    today = datetime.today().strftime("%Y-%m-%d")
    print(f"Fetching advanced data for {today}...")

    # ==========================================
    # 1. FETCH DAILY HEALTH & RECOVERY METRICS
    # ==========================================
    stats = api.get_stats(today)
    rhr = stats.get("restingHeartRate", "N/A")
    total_steps = stats.get("totalSteps", "N/A")
    
    # Sleep Data
    sleep_data = api.get_sleep_data(today)
    daily_sleep = sleep_data.get("dailySleepDTO", {})
    sleep_score = daily_sleep.get("sleepScores", {}).get("overall", {}).get("value", "N/A")
    sleep_seconds = daily_sleep.get("sleepTimeSeconds", 0)
    sleep_hours = round(sleep_seconds / 3600, 2) if sleep_seconds else "N/A"

    # HRV Data
    try:
        hrv_data = api.get_hrv_data(today)
        hrv_status = hrv_data.get("hrvSummary", {}).get("status", "N/A")
        hrv_weekly_avg = hrv_data.get("hrvSummary", {}).get("weeklyAvg", "N/A")
    except Exception:
        hrv_status, hrv_weekly_avg = "N/A", "N/A"

    # Training Readiness
    try:
        readiness_data = api.get_training_readiness(today)
        readiness_score = readiness_data.get("score", "N/A")
    except Exception:
        readiness_score = "N/A"

    # ==========================================
    # 2. FETCH LATEST ACTIVITY & SPLITS
    # ==========================================
    activities = api.get_activities(0, 1)
    latest_activity = activities[0] if activities else {}
    
    act_name = latest_activity.get("activityName", "N/A")
    aerobic_te = latest_activity.get("aerobicTrainingEffect", "N/A")
    anaerobic_te = latest_activity.get("anaerobicTrainingEffect", "N/A")
    activity_id = latest_activity.get("activityId")

    # Fetch lap splits if an activity exists
    laps_to_log = []
    if activity_id:
        try:
            splits_data = api.get_activity_splits(activity_id)
            lap_dtos = splits_data.get("lapDTOs", [])
            for idx, lap in enumerate(lap_dtos):
                lap_dist_km = round(lap.get("distance", 0) / 1000, 2)
                lap_duration_min = round(lap.get("duration", 0) / 60, 2)
                # Calculate pace in min/km if distance > 0
                if lap_dist_km > 0 and lap_duration_min > 0:
                    pace_min_per_km = round(lap_duration_min / lap_dist_km, 2)
                else:
                    pace_min_per_km = "N/A"
                
                lap_hr = lap.get("averageHR", "N/A")
                lap_cadence = lap.get("averageRunCadence", lap.get("averageCadence", "N/A"))
                lap_gct = lap.get("avgGroundContactTime", "N/A")
                lap_power = lap.get("avgPower", "N/A")
                
                laps_to_log.append([
                    today, act_name, idx + 1, lap_dist_km, pace_min_per_km, 
                    lap_hr, lap_cadence, lap_gct, lap_power, aerobic_te, anaerobic_te
                ])
        except Exception as e:
            print(f"Could not fetch laps for activity {activity_id}: {e}")

    # ==========================================
    # 3. CONNECT & WRITE TO GOOGLE SHEETS
    # ==========================================
    print("Connecting to Google Drive / Sheets...")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(CREDENTIALS_DICT, scope)
    client = gspread.authorize(creds)
    sh = client.open(SPREADSHEET_NAME)

    # --- Tab 1: Daily Readiness ---
    try:
        readiness_sheet = sh.worksheet("Daily_Readiness")
    except gspread.exceptions.WorksheetNotFound:
        readiness_sheet = sh.add_worksheet(title="Daily_Readiness", rows="100", cols="10")
        readiness_sheet.append_row(["Date", "Readiness Score", "HRV Status", "HRV Avg", "Sleep (hrs)", "Sleep Score", "Resting HR", "Steps"])

    readiness_sheet.append_row([
        today, readiness_score, hrv_status, hrv_weekly_avg, sleep_hours, sleep_score, rhr, total_steps
    ])

    # --- Tab 2: Workout Granularity (Splits) ---
    if laps_to_log:
        try:
            granularity_sheet = sh.worksheet("Workout_Granularity")
        except gspread.exceptions.WorksheetNotFound:
            granularity_sheet = sh.add_worksheet(title="Workout_Granularity", rows="500", cols="15")
            granularity_sheet.append_row(["Date", "Activity Name", "Lap", "Dist (km)", "Pace (min/km)", "Avg HR", "Cadence", "GCT (ms)", "Power (W)", "Aerobic TE", "Anaerobic TE"])

        for lap_row in laps_to_log:
            granularity_sheet.append_row(lap_row)
        print(f"Successfully logged {len(laps_to_log)} lap splits and daily health metrics!")
    else:
        print("Successfully logged daily health metrics (No new lap splits found for today).")

if __name__ == "__main__":
    main()

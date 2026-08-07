import os
import json
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from garminconnect import Garmin

# --- CONFIGURATION VIA ENVIRONMENT VARIABLES ---
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")
SPREADSHEET_NAME = "Garmin_Metrics_Log"  # Must match your Google Sheet name

# Load Google credentials JSON safely from the environment variable string
google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if not google_creds_json:
    raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable is missing.")
CREDENTIALS_DICT = json.loads(google_creds_json)

def main():
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        raise ValueError("Garmin credentials are not set in environment variables.")

    print("Connecting to Garmin Connect...")
    api = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    api.login()

    today = datetime.today().strftime("%Y-%m-%d")
    print(f"Fetching data for {today}...")

    # 1. Fetch Daily Health Metrics (Steps, RHR, Sleep)
    stats = api.get_stats(today)
    rhr = stats.get("restingHeartRate", "N/A")
    total_steps = stats.get("totalSteps", "N/A")
    
    # Fetch Sleep Data
    sleep_data = api.get_sleep_data(today)
    sleep_seconds = sleep_data.get("dailySleepDTO", {}).get("sleepTimeSeconds", 0)
    sleep_hours = round(sleep_seconds / 3600, 2) if sleep_seconds else "N/A"

    # 2. Fetch Latest Activity
    activities = api.get_activities(0, 1)  # Get the most recent activity
    latest_activity = activities[0] if activities else {}
    
    act_name = latest_activity.get("activityName", "N/A")
    act_type = latest_activity.get("activityType", {}).get("typeKey", "N/A")
    distance_km = round(latest_activity.get("distance", 0) / 1000, 2)
    duration_min = round(latest_activity.get("duration", 0) / 60, 2)
    avg_hr = latest_activity.get("averageHR", "N/A")

    # 3. Connect to Google Sheets using Dictionary credentials
    print("Connecting to Google Drive / Sheets...")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(CREDENTIALS_DICT, scope)
    client = gspread.authorize(creds)
    
    sheet = client.open(SPREADSHEET_NAME).sheet1

    # Ensure headers exist if sheet is empty
    if not sheet.get_all_values():
        sheet.append_row([
            "Date", "Activity Name", "Type", "Distance (km)", 
            "Duration (min)", "Avg HR", "Resting HR", "Sleep (hrs)", "Steps"
        ])

    # 4. Append Data Row
    row_data = [
        today, act_name, act_type, distance_km, 
        duration_min, avg_hr, rhr, sleep_hours, total_steps
    ]
    
    sheet.append_row(row_data)
    print("Successfully logged latest metrics and workout to Google Sheets!")

if __name__ == "__main__":
    main()
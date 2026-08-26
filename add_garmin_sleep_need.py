import argparse
import json
import os

SLEEP_NEED_URL = "/sleep-service/sleep/dailySleepData"


def _hours(minutes):
    if minutes is None or minutes == "":
        return None
    try:
        return round(float(minutes) / 60.0, 2)
    except (ValueError, TypeError):
        return None


def _humanize(value):
    if not isinstance(value, str) or not value:
        return value
    return value.replace("_", " ").strip().title()


def extract_sleep_need(data):
    """Extract Garmin's personalized sleep-need recommendation from dailySleepData."""
    if not isinstance(data, dict):
        return None
    dto = data.get("dailySleepDTO") or data.get("sleepDTO") or {}
    if not isinstance(dto, dict):
        return None
    need = dto.get("sleepNeed")
    next_need = dto.get("nextSleepNeed")
    if not isinstance(need, dict):
        return None

    result = {}
    if need.get("baseline") is not None:
        result["baseline_hours"] = _hours(need.get("baseline"))
    if need.get("actual") is not None:
        result["need_hours"] = _hours(need.get("actual"))

    for source, dest in (
        ("feedback", "feedback"),
        ("trainingFeedback", "training_feedback"),
        ("sleepHistoryAdjustment", "sleep_history_adjustment"),
        ("hrvAdjustment", "hrv_adjustment"),
        ("napAdjustment", "nap_adjustment"),
    ):
        value = need.get(source)
        if value not in (None, ""):
            result[dest] = _humanize(value)

    if isinstance(next_need, dict) and next_need.get("actual") is not None:
        result["next_need_hours"] = _hours(next_need.get("actual"))

    return result or None


def fetch_sleep_need(api, target_date_str):
    """Fetch sleep need from Garmin's dedicated dailySleepData endpoint."""
    try:
        data = api.connectapi(
            SLEEP_NEED_URL,
            params={"date": target_date_str, "nonSleepBufferMinutes": 60},
        )
    except Exception as exc:
        print(f"[sleep_need] Warning: could not fetch sleep need for {target_date_str}: {exc}")
        return None
    return extract_sleep_need(data)


def apply_sleep_need(payload, sleep_need):
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object payload")
    daily = payload.setdefault("daily_readiness", {})
    if sleep_need:
        daily["sleep_need"] = sleep_need
    else:
        daily.pop("sleep_need", None)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--json", default="data/latest.json")
    args = parser.parse_args()

    from garminconnect import Garmin

    token_dir = os.environ.get("GARMIN_TOKENSTORE", "./.garminconnect")
    api = Garmin()
    api.login(token_dir)
    sleep_need = fetch_sleep_need(api, args.date)

    with open(args.json, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    payload = apply_sleep_need(payload, sleep_need)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"[sleep_need] {'Added' if sleep_need else 'No'} sleep need for {args.date}")


if __name__ == "__main__":
    main()

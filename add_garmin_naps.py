import argparse
import json
import os
from datetime import datetime, timedelta
from garminconnect import Garmin


def parse_dt(value):
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    for parser in (
        lambda s: datetime.fromisoformat(s),
        lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
        lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M"),
    ):
        try:
            return parser(text)
        except (ValueError, TypeError):
            pass
    return None


def first_value(obj, keys):
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                return obj[key]
        for value in obj.values():
            found = first_value(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = first_value(value, keys)
            if found is not None:
                return found
    return None


def extract_naps(sleep_data):
    dto = sleep_data.get("dailySleepDTO", {}) if isinstance(sleep_data, dict) else {}
    nap_dtos = dto.get("dailyNapDTOS", []) if isinstance(dto, dict) else []
    return nap_dtos if isinstance(nap_dtos, list) else []


def nap_record(nap):
    start_raw = first_value(nap, ("napStartTimeLocal", "startTimeLocal", "startTime", "beginTime"))
    end_raw = first_value(nap, ("napEndTimeLocal", "endTimeLocal", "endTime", "finishTime"))
    start = parse_dt(start_raw)
    end = parse_dt(end_raw)
    if start is None and end is None:
        return None

    duration_sec = first_value(nap, ("durationInSeconds", "durationSeconds", "napTimeSeconds", "duration"))
    try:
        duration_min = round(float(duration_sec) / 60.0, 1) if duration_sec is not None else None
    except (ValueError, TypeError):
        duration_min = None
    if duration_min is None and start is not None and end is not None:
        duration_min = round((end - start).total_seconds() / 60.0, 1)

    actual_dt = start or end
    return {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "duration_min": duration_min,
        "type": first_value(nap, ("napType", "type")),
        "actual_date": actual_dt.date().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--json", default="data/latest.json")
    args = parser.parse_args()

    target = datetime.strptime(args.date, "%Y-%m-%d").date()
    previous = target - timedelta(days=1)

    token_dir = os.environ.get("GARMIN_TOKENSTORE", "./.garminconnect")
    api = Garmin()
    api.login(token_dir)

    records = []
    seen = set()
    for day in (target, previous):
        try:
            sleep_data = api.get_sleep_data(day.isoformat())
        except Exception as exc:
            print(f"[naps] Warning: could not fetch sleep data for {day}: {exc}")
            continue

        for nap in extract_naps(sleep_data):
            record = nap_record(nap)
            if not record:
                continue

            # Garmin can attach an afternoon nap to the following sleep record.
            # Therefore, target-date sleep data may legitimately contain a nap
            # whose actual date is the previous calendar day. The previous-date
            # lookup is restricted by actual timestamp to avoid unrelated data.
            if day == previous and record["actual_date"] != previous.isoformat():
                continue
            if day == target and record["actual_date"] not in (target.isoformat(), previous.isoformat()):
                continue

            key = (record["start"], record["end"], record["duration_min"])
            if key in seen:
                continue
            seen.add(key)
            record.pop("actual_date", None)
            record = {k: v for k, v in record.items() if v is not None}
            records.append(record)

    with open(args.json, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {args.json}")

    health = payload.setdefault("health_stats", {})
    readiness = payload.setdefault("daily_readiness", {})

    if records:
        records.sort(key=lambda item: item.get("start", ""))
        health["naps"] = records
    else:
        health.pop("naps", None)

    previous_naps = []
    for record in records:
        actual_date = (record.get("start") or record.get("end") or "")[:10]
        if actual_date == previous.isoformat():
            previous_naps.append(record)
    previous_nap = max(previous_naps, key=lambda item: item.get("end", item.get("start", ""))) if previous_naps else None
    nap_minutes = round(sum(float(record.get("duration_min") or 0) for record in records), 1)

    overnight = health.get("sleep_hours")
    if overnight is None:
        overnight = health.get("total_sleep_hours")
    combined_sleep = overnight
    if previous_nap and overnight is not None:
        combined_sleep = round(float(overnight) + float(previous_nap.get("duration_min") or 0) / 60.0, 2)

    health["nap_minutes"] = nap_minutes
    health["sleep_hours_including_previous_day_nap"] = combined_sleep
    health["previous_day_nap"] = previous_nap
    readiness["nap_minutes"] = nap_minutes
    readiness["sleep_hours_including_previous_day_nap"] = combined_sleep
    readiness["previous_day_nap"] = previous_nap

    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"[naps] Added {len(records)} nap(s) for {args.date}; previous-day nap={previous_nap is not None}")


if __name__ == "__main__":
    main()

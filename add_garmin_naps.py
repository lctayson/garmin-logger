import argparse
import json
from datetime import datetime, timedelta, timezone
from garminconnect import Garmin


def parse_dt(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if not isinstance(value, str):
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
    start_raw = first_value(nap, (
        "napStartTimeLocal", "napStartTimestampLocal", "startTimeLocal", "startTimestampLocal",
        "napStartTimeGMT", "napStartTimestampGMT", "startTimeGMT", "startTimestampGMT",
        "startTime", "beginTime",
    ))
    end_raw = first_value(nap, (
        "napEndTimeLocal", "napEndTimestampLocal", "endTimeLocal", "endTimestampLocal",
        "napEndTimeGMT", "napEndTimestampGMT", "endTimeGMT", "endTimestampGMT",
        "endTime", "finishTime",
    ))
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


def collect_naps(api, target):
    previous = target - timedelta(days=1)
    records = []
    seen = set()
    for queried_day in (target, previous):
        try:
            sleep_data = api.get_sleep_data(queried_day.isoformat())
        except Exception as exc:
            print(f"[naps] Warning: could not fetch sleep data for {queried_day}: {exc}")
            continue
        for nap in extract_naps(sleep_data):
            record = nap_record(nap)
            if not record:
                continue
            # A target-date sleep record may contain a nap from the previous calendar day.
            # A previous-date sleep record must contain a nap whose actual date is that previous day.
            if queried_day == previous and record["actual_date"] != previous.isoformat():
                continue
            if queried_day == target and record["actual_date"] not in (target.isoformat(), previous.isoformat()):
                continue
            key = (record["start"], record["end"], record["duration_min"])
            if key in seen:
                continue
            seen.add(key)
            record.pop("actual_date", None)
            records.append({k: v for k, v in record.items() if v is not None})
    records.sort(key=lambda item: item.get("start", ""))
    return records


def apply_naps_to_payload(payload, target, records):
    """Store detailed naps once and expose only the previous-day nap summary in readiness."""
    previous = target - timedelta(days=1)
    health = payload.setdefault("health_stats", {})
    daily = payload.setdefault("daily_readiness", {})

    if records:
        health["naps"] = records
    else:
        health.pop("naps", None)

    # The detailed nap list is authoritative. Do not duplicate its totals in health_stats.
    health.pop("nap_minutes", None)
    health.pop("sleep_hours_including_previous_day_nap", None)
    health.pop("previous_day_nap", None)

    previous_naps = [
        record for record in records
        if (record.get("start") or record.get("end") or "")[:10] == previous.isoformat()
    ]
    previous_nap_minutes = round(
        sum(float(record.get("duration_min") or 0) for record in previous_naps), 1
    )

    # Keep the readiness snapshot useful without duplicating the full nap object.
    daily["previous_day_nap"] = previous_nap_minutes if previous_naps else None
    overnight = daily.get("sleep_hours")
    if overnight is None:
        overnight = health.get("sleep_hours", health.get("total_sleep_hours"))
    daily["sleep_hours_including_previous_day_nap"] = (
        round(float(overnight) + previous_nap_minutes / 60.0, 2)
        if overnight is not None else None
    )
    daily.pop("nap_minutes", None)

    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--json", default="data/latest.json")
    args = parser.parse_args()
    target = datetime.strptime(args.date, "%Y-%m-%d").date()
    token_dir = __import__("os").environ.get("GARMIN_TOKENSTORE", "./.garminconnect")
    api = Garmin()
    api.login(token_dir)
    records = collect_naps(api, target)
    with open(args.json, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {args.json}")
    payload = apply_naps_to_payload(payload, target, records)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    previous_naps = [
        record for record in records
        if (record.get("start") or record.get("end") or "")[:10] == (target - timedelta(days=1)).isoformat()
    ]
    previous_nap_minutes = round(sum(float(r.get("duration_min") or 0) for r in previous_naps), 1)
    print(f"[naps] Added {len(records)} nap(s) for {args.date}; previous-day nap minutes={previous_nap_minutes}")


if __name__ == "__main__":
    main()

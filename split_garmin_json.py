"""Split the generated Garmin snapshot into daily and activity JSON files.

The generator still produces the existing combined latest.json / dated JSON as
an intermediate representation. This script separates that payload so the
relatively large activity/lap data can be retrieved independently from the
smaller daily health/readiness data.

Outputs for target date YYYY-MM-DD:
  data/YYYY/MM/YYYY-MM-DD_daily.json
  data/YYYY/MM/YYYY-MM-DD_activities.json
  data/latest_daily.json
  data/latest_activities.json

The two latest_* files are exact byte-for-byte copies of the dated files.
The old combined latest.json and dated YYYY-MM-DD.json are removed after the
split succeeds.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime


ACTIVITY_KEYS = ("activities", "activity_data", "activityData")


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def split_payload(payload: dict) -> tuple[dict, dict]:
    activity_key = next((key for key in ACTIVITY_KEYS if key in payload), None)
    if activity_key is None:
        raise KeyError(
            "Could not find the activity section. Expected one of: "
            + ", ".join(ACTIVITY_KEYS)
        )

    daily = {key: value for key, value in payload.items() if key != activity_key}
    activities = {
        "date": payload.get("date"),
        activity_key: payload.get(activity_key),
    }
    return daily, activities


def write_json(path: str, payload: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    latest_path = os.path.join(args.data_dir, "latest.json")
    if not os.path.isfile(latest_path):
        raise FileNotFoundError(f"Missing generated file: {latest_path}")

    payload = load_json(latest_path)
    target_date = args.date or payload.get("date")
    if not target_date:
        raise ValueError("Target date is missing from --date and generated JSON")
    target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    # Trust the payload date when it exists; this prevents accidentally writing
    # a manually requested historical run into today's directory.
    payload_date = payload.get("date")
    if payload_date and payload_date != target_date.isoformat():
        raise ValueError(
            f"Date mismatch: --date={target_date.isoformat()} but JSON date={payload_date}"
        )

    daily, activities = split_payload(payload)

    month_dir = os.path.join(
        args.data_dir,
        f"{target_date.year:04d}",
        f"{target_date.month:02d}",
    )
    os.makedirs(month_dir, exist_ok=True)

    dated_daily = os.path.join(month_dir, f"{target_date.isoformat()}_daily.json")
    dated_activities = os.path.join(month_dir, f"{target_date.isoformat()}_activities.json")
    latest_daily = os.path.join(args.data_dir, "latest_daily.json")
    latest_activities = os.path.join(args.data_dir, "latest_activities.json")

    # Write dated files first. Only after both succeed do we replace the latest
    # aliases, so a partial run cannot leave mismatched latest_* files.
    write_json(dated_daily, daily)
    write_json(dated_activities, activities)

    shutil.copyfile(dated_daily, latest_daily)
    shutil.copyfile(dated_activities, latest_activities)

    # Remove the old combined files only after all four desired files exist.
    old_dated = os.path.join(month_dir, f"{target_date.isoformat()}.json")
    if os.path.exists(old_dated):
        os.remove(old_dated)
    os.remove(latest_path)

    print(f"Created {dated_daily}")
    print(f"Created {dated_activities}")
    print(f"Updated {latest_daily}")
    print(f"Updated {latest_activities}")


if __name__ == "__main__":
    main()

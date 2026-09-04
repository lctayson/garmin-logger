"""Run the normal Garmin JSON generator with API-based enrichment."""
import argparse
import sys
from pathlib import Path

import garmin_to_json as generator
from activity_zones import add_activity_zones
from garmin_activity_enrichment import enrich_activity, _running_tolerance
from compact_metrics import compact_file
from config import get_timezone, resolve_timezone

_original_get_activities = generator.get_activities
_original_get_training_history = generator.get_training_history


def get_activities(api, target_date):
    date_str = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
    activities = _original_get_activities(api, date_str)
    return add_activity_zones(api, [enrich_activity(api, dict(a)) for a in activities or []])


def get_training_history(api, target_date):
    history = _original_get_training_history(api, target_date)
    tolerance = _running_tolerance(api, target_date)
    if tolerance is not None:
        history["running_tolerance"] = tolerance
    return history


generator.get_activities = get_activities
generator.get_training_history = get_training_history


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--timezone", help="IANA timezone override, e.g. America/New_York")
    args, remaining = parser.parse_known_args()

    timezone_name = resolve_timezone(args.timezone)
    generator.LOCAL_TZ = get_timezone(args.timezone)
    sys.argv = [sys.argv[0], *remaining]

    print(f"Using timezone: {timezone_name}")
    generator.main()

    # Keep the generated metrics canonical and analysis-friendly. The normal
    # generator remains the Garmin API source-of-truth; this only removes
    # redundant representations from the saved JSON.
    latest_metrics = Path("data/latest_metrics.json")
    if latest_metrics.exists():
        changed = compact_file(latest_metrics)
        print("Compacted data/latest_metrics.json" if changed else "Metrics already compact")


if __name__ == "__main__":
    main()

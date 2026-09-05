"""Run the normal Garmin JSON generator with API-based enrichment."""
import argparse
import sys

import garmin_to_json as generator
from activity_zones import add_activity_zones
from garmin_activity_enrichment import enrich_activity, _running_tolerance
from activity_units import apply_user_units
from recovery_hr import add_recovery_hr
from config import get_timezone, resolve_timezone

_original_get_activities = generator.get_activities
_original_get_training_history = generator.get_training_history


def _add_activity_recovery_hr(api, activity):
    """Copy Garmin's stored two-minute recovery-HR drop when available."""
    if not isinstance(activity, dict) or not activity.get("activityId"):
        return activity
    try:
        detail = api.get_activity(activity["activityId"]) or {}
    except Exception:
        return activity
    summary = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    value = summary.get("recoveryHeartRate")
    if value is None and isinstance(detail, dict):
        value = detail.get("recoveryHeartRate")
    if value is not None:
        try:
            activity["recovery_hr"] = round(float(value))
        except (TypeError, ValueError):
            pass
    return activity


def get_activities(api, target_date):
    date_str = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
    activities = _original_get_activities(api, date_str)
    enriched = [enrich_activity(api, dict(a)) for a in activities or []]
    enriched = [_add_activity_recovery_hr(api, a) for a in enriched]
    enriched = [add_recovery_hr(api, a) for a in enriched]
    enriched = add_activity_zones(api, enriched)
    # Keep internal calculations in canonical metric units, then convert only
    # the final activity/split representation to the Garmin account's
    # measurement preference. Unit metadata is stored once per activity and
    # applies to both the activity-level values and its splits.
    return apply_user_units(api, enriched)


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


if __name__ == "__main__":
    main()

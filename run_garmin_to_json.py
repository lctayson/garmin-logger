"""Run the normal Garmin JSON generator with API-based enrichment."""
import garmin_to_json as generator
from activity_zones import add_activity_zones
from garmin_activity_enrichment import enrich_activity, _running_tolerance

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

if __name__ == "__main__":
    generator.main()

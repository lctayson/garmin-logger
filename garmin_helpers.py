import sys
from datetime import timedelta

# Keep the existing helper functions above unchanged. Activity export is defined
# below using Garmin's date-specific endpoint.

def _normalize_activity_response(raw):
    """Normalize Garmin's single-day activity response to a list."""
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    for key in ('activityList', 'activities', 'activityData', 'activityDTOs', 'activityDTO'):
        value = raw.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
    return []

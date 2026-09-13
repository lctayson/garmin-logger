"""
Covers a bug where multisport events (triathlons/duathlons) picked the
longest individual leg's name for the dated activities filename (e.g.
"bohol-5150-cycling") instead of the overall event name ("bohol-5150").

Two things had to be fixed together:
  1. activity_units.py's _convert_activity() silently dropped the camelCase
     "parentActivityId" field set by garmin_helpers.get_activities() for
     multisport legs -- it was never renamed to the snake_case
     "parent_activity_id" that the rest of the pipeline expects, so it never
     survived unit conversion.
  2. split_garmin_json.py's normalize_activity() had the same gap, and
     primary_activity_slug() needed to group legs sharing a
     parent_activity_id and compare/name them as one activity instead of
     picking whichever leg is individually longest.
"""

from activity_units import _convert_activity
from split_garmin_json import (
    normalize_activity,
    normalize_activities,
    primary_activity_slug,
)


class _FakeApi:
    """_convert_activity() only needs a unit-system check; _unit_system()
    falls back to metric when the api object has no get_unit_system()."""

    pass


BOHOL_LEGS_RAW = [
    {
        "activityId": 19715571044,
        "name": "Bohol 5150 - Swim",
        "type": "open_water_swimming",
        "distance_km": 1.5,
        "parentActivityId": 19715571043,
        "time": "20:00",
    },
    {
        "activityId": 19715571045,
        "name": "Transition 1 (T1)",
        "type": "transition",
        "parentActivityId": 19715571043,
        "time": "3:00",
    },
    {
        "activityId": 19715571046,
        "name": "Bohol 5150 - Cycling",
        "type": "cycling",
        "distance_km": 40.0,
        "parentActivityId": 19715571043,
        "time": "1:30:00",
    },
    {
        "activityId": 19715571047,
        "name": "Transition 2 (T2)",
        "type": "transition",
        "parentActivityId": 19715571043,
        "time": "2:00",
    },
    {
        "activityId": 19715571048,
        "name": "Bohol 5150 - Running",
        "type": "running",
        "distance_km": 10.0,
        "parentActivityId": 19715571043,
        "time": "45:00",
    },
]


def test_convert_activity_renames_parent_activity_id():
    """activity_units._convert_activity() must preserve parentActivityId
    (as snake_case) instead of silently dropping it."""
    leg = dict(BOHOL_LEGS_RAW[2])  # the cycling leg
    converted = _convert_activity(leg, _FakeApi())
    assert converted.get("parent_activity_id") == 19715571043
    assert "parentActivityId" not in converted


def test_normalize_activity_renames_parent_activity_id():
    """split_garmin_json.normalize_activity() must also preserve it, in
    case an activity ever reaches this stage without having already been
    through activity_units.py."""
    leg = {"name": "Bohol 5150 - Cycling", "type": "cycling", "time": "1:30:00", "parentActivityId": 19715571043}
    normalized = normalize_activity(leg)
    assert normalized.get("parent_activity_id") == 19715571043
    assert "parentActivityId" not in normalized


def test_triathlon_slug_uses_event_name_not_longest_leg():
    """Regression test for the reported bug: a triathlon's dated activities
    filename must use the overall event name, not whichever leg (usually
    the bike) happens to be the longest individually."""
    converted = [_convert_activity(dict(leg), _FakeApi()) for leg in BOHOL_LEGS_RAW]
    normalized = normalize_activities(converted)

    assert all(a.get("parent_activity_id") == 19715571043 for a in normalized)
    assert primary_activity_slug(normalized) == "bohol-5150"


def test_triathlon_total_duration_beats_an_unrelated_same_day_walk():
    """The grouped triathlon's combined duration (all legs + transitions)
    must still win the day even against another standalone activity."""
    converted = [_convert_activity(dict(leg), _FakeApi()) for leg in BOHOL_LEGS_RAW]
    normalized = normalize_activities(converted)
    normalized.append(
        normalize_activity({"name": "Evening Walk", "type": "walking", "time": "15:00"})
    )

    assert primary_activity_slug(normalized) == "bohol-5150"


def test_single_activity_day_is_unaffected():
    """Non-multisport days (no parent_activity_id anywhere) must behave
    exactly as before -- this fix must not change ordinary-day behavior."""
    activities = [
        normalize_activity(
            {"name": "Malolos - 5 x 3min VO2 Intervals", "type": "running", "time": "42:23", "moving_time": "42:20"}
        )
    ]
    assert primary_activity_slug(activities) == "malolos-5-x-3min-vo2-intervals"


def test_no_activity_day_returns_none():
    assert primary_activity_slug([]) is None


def test_scalar_target_arrays_render_inline():
    """Plain scalar lists like a [min, max] target range should print on
    one line for readability/filesize, without affecting table (columns/
    data) formatting or lists of dicts."""
    from split_garmin_json import _dump_pretty
    import json as _json

    payload = {
        "load_balance": {
            "aerobic_low": 458.4,
            "aerobic_low_target": [303, 822],
            "load_focus": "Anaerobic Shortage",
        },
        "body_battery_trend": {
            "columns": ["date", "charged"],
            "data": [["2026-09-02", 55], ["2026-09-03", 68]],
        },
    }
    rendered = _dump_pretty(payload)

    assert '"aerobic_low_target": [303, 822]' in rendered
    # table rows are lists-of-lists, not pure scalar lists -- must stay one row per line
    assert '["2026-09-02", 55],' in rendered
    # content survives a full round-trip unchanged, only whitespace differs
    assert _json.loads(rendered) == payload
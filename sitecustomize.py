"""Compatibility shim for garmin_to_json.py.

The historical helper block was accidentally replaced by a placeholder in
one commit. Python loads sitecustomize during interpreter startup, so expose
the restored helpers as builtins until garmin_to_json.py can be consolidated.
"""
import builtins
from garmin_helpers import (
    get_training_status_details,
    get_metric_trend,
    get_body_battery_trend,
    get_activities,
)

builtins.get_training_status_details = get_training_status_details
builtins.get_metric_trend = get_metric_trend
builtins.get_body_battery_trend = get_body_battery_trend
builtins.get_activities = get_activities

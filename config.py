"""Project-wide runtime configuration.

Users can edit TIMEZONE here for the simplest setup. Environment variables and
CLI options can override it for automated or ad-hoc runs.
"""

import os
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Manila"
TIMEZONE_ENV_VAR = "GARMIN_TIMEZONE"


def resolve_timezone(cli_timezone=None):
    """Return the effective IANA timezone name.

    Precedence: CLI argument > GARMIN_TIMEZONE > config.py > UTC fallback.
    """
    value = cli_timezone or os.getenv(TIMEZONE_ENV_VAR) or TIMEZONE or "UTC"
    try:
        ZoneInfo(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"Invalid timezone '{value}'. Use an IANA timezone such as "
            "Asia/Manila, America/New_York, Europe/London, or UTC."
        )
    return value


def get_timezone(cli_timezone=None):
    """Return the effective timezone as a ZoneInfo object."""
    return ZoneInfo(resolve_timezone(cli_timezone))


# Heading of the active dated plan in training_context.md. Change this once when
# switching training blocks, or override with GARMIN_TRAINING_PLAN_HEADING.
TRAINING_PLAN_HEADING = "# BHM 2027 Training Plan"
TRAINING_PLAN_HEADING_ENV_VAR = "GARMIN_TRAINING_PLAN_HEADING"


def resolve_training_plan_heading():
    """Return the active plan heading (environment override takes precedence)."""
    return os.getenv(TRAINING_PLAN_HEADING_ENV_VAR, TRAINING_PLAN_HEADING).strip()

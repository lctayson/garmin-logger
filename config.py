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

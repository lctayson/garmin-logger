"""Apply Garmin account measurement preferences to user-facing metrics JSON."""
from __future__ import annotations

KM_TO_MI = 0.621371192237334
M_TO_FT = 3.280839895013123
CM_TO_IN = 0.3937007874015748


def _imperial(system):
    return str(system or "metric").lower() in {"statute_us", "statute_uk", "statute"}


def _convert_value(key, value, imperial):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    if key.endswith("_km"):
        return round(value * (KM_TO_MI if imperial else 1.0), 2)
    if key in {"elevation_gain_m", "elevation_loss_m"} or key.endswith("_elevation_m") or key == "elevation_m":
        return round(value * (M_TO_FT if imperial else 1.0), 1)
    if key in {"stride_length_m", "avg_stride_length_m"}:
        return round(value * (M_TO_FT if imperial else 1.0), 2)
    if key in {"vertical_oscillation_cm", "avg_vertical_oscillation_cm"}:
        return round(value * (CM_TO_IN if imperial else 1.0), 2)
    return value


def _rename_key(key, imperial):
    if key.endswith("_km"):
        return key[:-3]
    if key in {"elevation_gain_m", "elevation_loss_m"} or key.endswith("_elevation_m") or key == "elevation_m":
        return key[:-2]
    if key in {"stride_length_m", "avg_stride_length_m"}:
        return "stride_length"
    if key in {"vertical_oscillation_cm", "avg_vertical_oscillation_cm"}:
        return "vertical_oscillation"
    return key


def _transform(obj, imperial):
    if isinstance(obj, list):
        return [_transform(item, imperial) for item in obj]
    if not isinstance(obj, dict):
        return obj
    if isinstance(obj.get("columns"), list) and isinstance(obj.get("data"), list):
        original_columns = obj["columns"]
        columns = [_rename_key(column, imperial) if isinstance(column, str) else column for column in original_columns]
        data = []
        for row in obj["data"]:
            if not isinstance(row, list):
                data.append(_transform(row, imperial))
                continue
            transformed = []
            for column, value in zip(original_columns, row):
                if isinstance(value, (dict, list)):
                    transformed.append(_transform(value, imperial))
                else:
                    transformed.append(_convert_value(column, value, imperial))
            data.append(transformed + row[len(original_columns):])
        out = dict(obj)
        out["columns"] = columns
        out["data"] = data
        return out
    out = {}
    for key, value in obj.items():
        new_key = _rename_key(key, imperial)
        new_value = _transform(value, imperial) if isinstance(value, (dict, list)) else _convert_value(key, value, imperial)
        if new_key in out and new_key != key:
            raise ValueError(f"Metrics unit conversion key collision: {key} -> {new_key}")
        out[new_key] = new_value
    return out


def apply_metrics_units(metrics, measurement_system):
    """Convert variable-unit metrics once, using Garmin account preference."""
    if not isinstance(metrics, dict):
        return metrics
    imperial = _imperial(measurement_system)
    out = _transform(metrics, imperial)
    out.pop("_measurement_system", None)
    out["units"] = {
        "distance": "mi" if imperial else "km",
        "pace": "min/mi" if imperial else "min/km",
        "elevation": "ft" if imperial else "m",
        "stride_length": "ft" if imperial else "m",
        "vertical_oscillation": "in" if imperial else "cm",
        "temperature": "°F" if imperial else "°C",
        "wind_speed": "mph" if imperial else "m/s",
        "precipitation": "in" if imperial else "mm",
    }
    return out

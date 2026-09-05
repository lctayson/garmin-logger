"""Apply Garmin account measurement preferences to user-facing metrics JSON."""
from __future__ import annotations

KM_TO_MI = 0.621371192237334
M_TO_FT = 3.280839895013123


def _imperial(system):
    return str(system or "metric").lower() in {"statute_us", "statute_uk", "statute"}


def _convert_value(key, value, imperial):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    if key.endswith("_distance_km") or key == "distance_km" or key.endswith("_km"):
        return round(value * (KM_TO_MI if imperial else 1.0), 2)
    if key in {"elevation_gain_m", "elevation_loss_m"} or key.endswith("_elevation_m"):
        return round(value * (M_TO_FT if imperial else 1.0), 1)
    return value


def _rename_key(key):
    if key.endswith("_distance_km"):
        return key[:-3]
    if key == "distance_km":
        return "distance"
    if key.endswith("_km"):
        return key[:-3]
    if key in {"elevation_gain_m", "elevation_loss_m"}:
        return key[:-2]
    if key.endswith("_elevation_m"):
        return key[:-2]
    return key


def _transform(obj, imperial):
    if isinstance(obj, list):
        return [_transform(item, imperial) for item in obj]
    if not isinstance(obj, dict):
        return obj

    # Columnar trend tables need their column names and row values transformed
    # together so the schema remains internally consistent.
    if isinstance(obj.get("columns"), list) and isinstance(obj.get("data"), list):
        original_columns = obj["columns"]
        columns = [_rename_key(column) if isinstance(column, str) else column for column in original_columns]
        data = []
        for row in obj["data"]:
            if not isinstance(row, list):
                data.append(_transform(row, imperial))
                continue
            data.append([
                _convert_value(column, value, imperial) for column, value in zip(original_columns, row)
            ] + row[len(original_columns):])
        out = dict(obj)
        out["columns"] = columns
        out["data"] = data
        return out

    out = {}
    for key, value in obj.items():
        new_key = _rename_key(key)
        if isinstance(value, (dict, list)):
            new_value = _transform(value, imperial)
        else:
            new_value = _convert_value(key, value, imperial)
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
    out["units"] = {
        "distance": "mi" if imperial else "km",
        "elevation": "ft" if imperial else "m",
    }
    return out

from compact_metrics import compact_file
from metrics_units import apply_metrics_units


def test_metric_units_use_unit_neutral_keys():
    metrics = {
        "date": "2026-09-09",
        "training_history": {"7_day": {"distance_km": 34.32}},
        "trend_recent_daily": {
            "columns": ["date", "distance_km", "elevation_m"],
            "data": [["2026-09-09", 6.1, 12.0]],
        },
        "_measurement_system": "metric",
    }

    result = apply_metrics_units(metrics, "metric")

    assert result["units"] == {
        "distance": "km",
        "pace": "min/km",
        "elevation": "m",
        "stride_length": "m",
        "vertical_oscillation": "cm",
        "temperature": "°C",
        "wind_speed": "m/s",
        "precipitation": "mm",
    }
    assert result["training_history"]["7_day"]["distance"] == 34.32
    assert result["trend_recent_daily"]["columns"] == ["date", "distance", "elevation"]
    assert result["trend_recent_daily"]["data"][0][1:] == [6.1, 12.0]
    assert "_measurement_system" not in result


def test_imperial_units_convert_and_rename_variable_unit_metrics():
    metrics = {
        "date": "2026-09-09",
        "training_history": {
            "distance_km": 10.0,
            "elevation_gain_m": 100.0,
            "stride_length_m": 1.0,
            "vertical_oscillation_cm": 8.0,
        },
        "trend_recent_daily": {
            "columns": ["date", "distance_km", "elevation_m"],
            "data": [["2026-09-09", 10.0, 100.0]],
        },
        "_measurement_system": "statute_us",
    }

    result = apply_metrics_units(metrics, "statute_us")

    assert result["units"] == {
        "distance": "mi",
        "pace": "min/mi",
        "elevation": "ft",
        "stride_length": "ft",
        "vertical_oscillation": "in",
        "temperature": "°F",
        "wind_speed": "mph",
        "precipitation": "in",
    }
    assert result["training_history"]["distance"] == 6.21
    assert result["training_history"]["elevation_gain"] == 328.1
    assert result["training_history"]["stride_length"] == 3.28
    assert result["training_history"]["vertical_oscillation"] == 3.15
    assert result["trend_recent_daily"]["columns"] == ["date", "distance", "elevation"]
    assert result["trend_recent_daily"]["data"][0][1:] == [6.21, 328.1]
    assert "_measurement_system" not in result


def test_compact_file_normalizes_legacy_metric_keys_using_existing_units(tmp_path):
    path = tmp_path / "latest_metrics.json"
    path.write_text(
        '{\n'
        '  "date": "2026-09-09",\n'
        '  "training_history": {"7_day": {"distance_km": 34.32}},\n'
        '  "units": {"distance": "km", "elevation": "m"}\n'
        '}\n',
        encoding="utf-8",
    )

    assert compact_file(path)
    result = __import__("json").loads(path.read_text(encoding="utf-8"))

    assert result["training_history"]["7_day"]["distance"] == 34.32
    assert "distance_km" not in result["training_history"]["7_day"]
    assert result["units"]["distance"] == "km"


def test_compact_file_converts_legacy_metric_keys_for_imperial_units(tmp_path):
    path = tmp_path / "latest_metrics.json"
    path.write_text(
        '{\n'
        '  "date": "2026-09-09",\n'
        '  "training_history": {"7_day": {"distance_km": 10.0}},\n'
        '  "units": {"distance": "mi", "pace": "min/mi", "elevation": "ft"}\n'
        '}\n',
        encoding="utf-8",
    )

    assert compact_file(path)
    result = __import__("json").loads(path.read_text(encoding="utf-8"))

    assert result["training_history"]["7_day"]["distance"] == 6.21
    assert "distance_km" not in result["training_history"]["7_day"]
    assert result["units"]["distance"] == "mi"

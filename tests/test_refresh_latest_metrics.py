import json

from split_garmin_json import refresh_latest_metrics


def test_refresh_latest_metrics_copies_today_metrics(tmp_path):
    dated = tmp_path / "metrics_2026-09-09.json"
    dated.write_text(json.dumps({"date": "2026-09-09", "daily_readiness": {"sleep_score": 54}}), encoding="utf-8")

    assert refresh_latest_metrics(
        str(tmp_path),
        __import__("datetime").date(2026, 9, 9),
        str(dated),
        __import__("datetime").date(2026, 9, 9),
    ) is True

    latest = json.loads((tmp_path / "latest_metrics.json").read_text(encoding="utf-8"))
    assert latest["date"] == "2026-09-09"
    assert latest["daily_readiness"]["sleep_score"] == 54


def test_refresh_latest_metrics_does_not_replace_latest_for_historical_date(tmp_path):
    dated = tmp_path / "metrics_2026-09-08.json"
    dated.write_text(json.dumps({"date": "2026-09-08"}), encoding="utf-8")
    latest = tmp_path / "latest_metrics.json"
    latest.write_text(json.dumps({"date": "2026-09-09"}), encoding="utf-8")

    assert refresh_latest_metrics(
        str(tmp_path),
        __import__("datetime").date(2026, 9, 8),
        str(dated),
        __import__("datetime").date(2026, 9, 9),
    ) is False

    assert json.loads(latest.read_text(encoding="utf-8"))["date"] == "2026-09-09"

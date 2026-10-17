from generate_ai_analysis import _compact_context, _published_sheet_csv_url


SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTv8AJfthvUUbO3w8H5H8cBQ2Mq0t1-huuJnE-wo9vZVYYRJ-9s14pLUw9NQlGidPqOeIeDubRdCWaH/"
    "pubhtml?gid=810767784&single=true"
)


def test_published_sheet_url_converts_to_csv_export():
    url = _published_sheet_csv_url(SHEET_URL)
    assert url.endswith("/pub?gid=810767784&output=csv")


def test_compact_context_includes_live_sheet_plan(monkeypatch):
    import generate_ai_analysis

    monkeypatch.setattr(
        generate_ai_analysis,
        "_fetch_published_training_plan",
        lambda url: "| Week | Monday | Tuesday |\n| --- | --- | --- |\n| W4 | Strength | SUT 3x8min |",
    )
    context = """Coaching notes.

# BHM 2027 Training Plan

Source of truth: the updated BHM 2027 Plan spreadsheet.

> [Open Live BHM 2027 Training Plan (Google Sheets)](SHEET_URL)
""".replace("SHEET_URL", SHEET_URL)

    compact = _compact_context(context, "2026-10-17")

    assert "Coaching notes." in compact
    assert "Live BHM 2027 training plan" in compact
    assert "SUT 3x8min" in compact
    assert "Source of truth" in compact

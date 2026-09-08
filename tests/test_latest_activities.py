import json
from pathlib import Path
from split_garmin_json import refresh_latest_activities

def read_latest(path):
    return json.loads((path / "latest_activities.json").read_text(encoding="utf-8"))

def test_latest_activities_split_has_elapsed_time_next_to_time(tmp_path):
    source={"date":"2026-09-08","activities":[{"activityId":1,"activity_splits":{"columns":["step_type","lap","time","avg_pace"],"data":[["WARMUP",1,"10:01","7:23"],["ACTIVE",2,"3:00","5:12"]]}}]}
    p=tmp_path/"source.json"; p.write_text(json.dumps(source),encoding="utf-8")
    refresh_latest_activities(p,tmp_path/"latest_activities.json")
    s=read_latest(tmp_path)["activities"][0]["splits"]
    assert s["columns"][:4]==["step_type","lap","time","elapsed_time"]
    assert s["data"][0][:4]==["WARMUP",1,"10:01","10:01"]
    assert s["data"][1][:4]==["ACTIVE",2,"3:00","3:00"]

def test_latest_activities_has_no_legacy_duration_fields():
    a=read_latest(Path("data"))["activities"][0]
    assert "duration_min" not in a
    assert "aerobic_te" not in a
    assert "anaerobic_te" not in a
    assert "training_effect_label" not in a

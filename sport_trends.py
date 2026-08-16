from datetime import timedelta
from garmin_helpers import get_training_status_details


def _deep_get(d, keys, default=None):
    if not isinstance(d, dict):
        return default
    for key in keys:
        v = d
        for part in key.split('.'):
            if isinstance(v, dict) and part in v:
                v = v[part]
            else:
                v = None
                break
        if v is not None and v != '':
            return v
    return default


def _sport(activity):
    raw = str(_deep_get(activity, ['activityType.typeKey','activityType','sport','sportType','type'], '') or '').lower()
    if 'run' in raw or 'jog' in raw:
        return 'running'
    if any(x in raw for x in ('cycl','bike','biking')):
        return 'cycling'
    if 'swim' in raw:
        return 'swimming'
    if any(x in raw for x in ('multi','triathlon','duathlon','aquathlon')):
        return 'multisport'
    if 'transition' in raw:
        return 'transition'
    return 'other'


def _child_ids(api, parent_id):
    try:
        detail = api.get_activity(parent_id)
    except Exception:
        return []
    meta = detail.get('metadataDTO', {}) if isinstance(detail, dict) else {}
    ids = meta.get('childIds') or meta.get('childActivityIds') or detail.get('childIds') or detail.get('childActivityIds') or []
    if isinstance(ids, dict):
        ids = list(ids.values())
    return [x for x in ids if x]


def _expand(api, activities):
    out = []
    for act in activities or []:
        if _sport(act) != 'multisport' or not act.get('activityId'):
            out.append(act)
            continue
        ids = _child_ids(api, act['activityId'])
        if not ids:
            out.append(act)
            continue
        for cid in ids:
            try:
                detail = api.get_activity(cid)
            except Exception:
                continue
            summary = detail.get('summaryDTO', {}) if isinstance(detail, dict) else {}
            typ = _deep_get(detail, ['activityTypeDTO.typeKey','activityType.typeKey','activityType'], '') or ''
            out.append({
                'activityId': cid,
                'activityType': {'typeKey': typ},
                'distance': summary.get('distance') or detail.get('distance') or 0,
                'duration': summary.get('duration') or detail.get('duration') or 0,
                'trainingLoad': _deep_get(summary, ['trainingLoad','exerciseLoad']) or _deep_get(detail, ['trainingLoad','exerciseLoad','activityTrainingLoad'])
            })
    return out


def _load(act):
    value = _deep_get(act, ['trainingLoad','exerciseLoad','activityTrainingLoad','summaryDTO.trainingLoad','summaryDTO.exerciseLoad'])
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _totals(activities):
    sports = {s: {'activity_count':0,'distance_km':0.0,'duration_hours':0.0,'exercise_load':0.0,'load_available':False} for s in ('running','cycling','swimming','multisport','other','transition')}
    total = {'activity_count':0,'distance_km':0.0,'duration_hours':0.0,'exercise_load':0.0,'load_available':False}
    for act in activities:
        sport = _sport(act)
        distance = float(act.get('distance') or 0) / 1000.0
        duration = float(act.get('duration') or act.get('elapsedDuration') or 0) / 3600.0
        load = _load(act)
        b = sports[sport]
        b['activity_count'] += 1
        b['distance_km'] += distance
        b['duration_hours'] += duration
        total['activity_count'] += 1
        total['distance_km'] += distance
        total['duration_hours'] += duration
        if load is not None:
            b['exercise_load'] += load
            b['load_available'] = True
            total['exercise_load'] += load
            total['load_available'] = True
    def clean(b):
        out = {'activity_count':b['activity_count'],'distance_km':round(b['distance_km'],2),'duration_hours':round(b['duration_hours'],2)}
        if b['load_available']:
            out['exercise_load'] = round(b['exercise_load'],1)
        return out
    return {k:clean(v) for k,v in sports.items()}, clean(total)


def get_metric_trend(api, target_date, days=14, interval=1):
    """Sport-aware daily/weekly trend; multisport parents are expanded into child legs."""
    from garmin_to_json import get_health_stats
    if days <= 0:
        return []
    if interval == 1:
        windows = [(target_date-timedelta(days=i), target_date-timedelta(days=i)) for i in reversed(range(days))]
    else:
        windows = []
        end = target_date
        remaining = days
        while remaining > 0:
            n = min(interval, remaining)
            start = end - timedelta(days=n-1)
            windows.append((start,end))
            end = start - timedelta(days=1)
            remaining -= n
        windows.reverse()

    result = []
    for start, end in windows:
        try:
            activities = api.get_activities_by_date(start.isoformat(), end.isoformat())
        except Exception:
            activities = []
        activities = _expand(api, activities)
        sports, total = _totals(activities)
        try:
            health = get_health_stats(api, end.isoformat())
        except Exception:
            health = {}
        try:
            status = get_training_status_details(api, end.isoformat())
        except Exception:
            status = {}
        entry = {
            'date': end.isoformat(),
            'window_start': start.isoformat(),
            'window_end': end.isoformat(),
            'window_days': (end-start).days+1,
            'resting_heart_rate': health.get('resting_heart_rate'),
            'hrv_last_night_avg_ms': _deep_get(health,['hrv.last_night_avg_ms']),
            'hrv_seven_day_avg_ms': _deep_get(health,['hrv.seven_day_avg_ms']),
            'total_sleep_hours': health.get('total_sleep_hours'),
            'sleep_score': health.get('sleep_score'),
            'vo2_max': _deep_get(status,['vo2_max.value']),
            'training_status': status.get('status'),
            'acute_load': _deep_get(status,['training_load.acute_load']),
            'chronic_load': _deep_get(status,['training_load.chronic_load']),
            'acwr': _deep_get(status,['training_load.acwr']),
            'acwr_status': _deep_get(status,['training_load.acwr_status']),
            'activity_count': total['activity_count'],
            'total_endurance_duration_hours': total['duration_hours'],
            'total_endurance_distance_km': total['distance_km'],
            'sport_volume': {s:v for s,v in sports.items() if v['activity_count'] > 0}
        }
        if 'exercise_load' in total:
            entry['total_exercise_load'] = total['exercise_load']
        result.append({k:v for k,v in entry.items() if v is not None})
    return result

import sys
from datetime import timedelta


def humanize_enum(s):
    if not isinstance(s, str) or not s:
        return None
    return s.replace('_', ' ').strip().title()


def _safe_float(val, decimals=2):
    if val is None or val == 'N/A' or val == '':
        return None
    try:
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if val is None or val == 'N/A' or val == '':
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


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


def get_training_status_details(api, target_date_str):
    try:
        raw = api.get_training_status(target_date_str)
    except Exception as e:
        print(f'[training_status] Warning: {e}', file=sys.stderr)
        return {}
    if not isinstance(raw, dict):
        return {}
    result = {}
    status_block = raw.get('mostRecentTrainingStatus', {}) or {}
    device_map = status_block.get('latestTrainingStatusData', {}) or {}
    device = next(iter(device_map.values()), {}) if isinstance(device_map, dict) else {}
    phrase = device.get('trainingStatusFeedbackPhrase')
    if phrase:
        parts = phrase.split('_')
        result['status'] = f'{parts[0].title()} {parts[1] if len(parts) > 1 else ""}'.strip()
    else:
        codes = {0:'No Status',1:'Detraining',2:'Recovery',3:'Maintaining',4:'Productive',5:'Peaking',6:'Overreaching',7:'Unproductive',8:'Strained'}
        result['status'] = codes.get(_safe_int(device.get('trainingStatus')), device.get('trainingStatus'))
    acute = device.get('acuteTrainingLoadDTO', {}) or {}
    if any(acute.get(k) is not None for k in ('dailyTrainingLoadAcute','dailyTrainingLoadChronic','dailyAcuteChronicWorkloadRatio','acwrStatus')):
        result['training_load'] = {
            'acute_load': _safe_int(acute.get('dailyTrainingLoadAcute')),
            'chronic_load': _safe_int(acute.get('dailyTrainingLoadChronic')),
            'chronic_load_range': {'min': _safe_float(acute.get('minTrainingLoadChronic'),1), 'max': _safe_float(acute.get('maxTrainingLoadChronic'),1)},
            'acwr': _safe_float(acute.get('dailyAcuteChronicWorkloadRatio'),2),
            'acwr_percent': _safe_int(acute.get('acwrPercent')),
            'acwr_status': humanize_enum(acute.get('acwrStatus')) if isinstance(acute.get('acwrStatus'),str) else acute.get('acwrStatus')
        }
        result['training_load'] = {k:v for k,v in result['training_load'].items() if v is not None}
    # Prefer Garmin Training Readiness: recoveryTime is reported in minutes.
    recovery_hours = get_recovery_time_hours(api, target_date_str, raw)
    if recovery_hours is not None:
        result['recovery_time_hours'] = recovery_hours
    balance = raw.get('mostRecentTrainingLoadBalance',{}) or {}
    bmap = balance.get('metricsTrainingLoadBalanceDTOMap',{}) or {}
    be = next(iter(bmap.values()),{}) if isinstance(bmap,dict) else {}
    focus = be.get('trainingLoadBalanceFeedbackPhrase') or be.get('trainingBalanceFeedbackPhrase')
    if focus:
        result['load_focus'] = humanize_enum(focus)
    monthly = {
        'aerobic_low': _safe_float(be.get('monthlyLoadAerobicLow'),1),
        'aerobic_low_target_min': _safe_int(be.get('monthlyLoadAerobicLowTargetMin')),
        'aerobic_low_target_max': _safe_int(be.get('monthlyLoadAerobicLowTargetMax')),
        'aerobic_high': _safe_float(be.get('monthlyLoadAerobicHigh'),1),
        'aerobic_high_target_min': _safe_int(be.get('monthlyLoadAerobicHighTargetMin')),
        'aerobic_high_target_max': _safe_int(be.get('monthlyLoadAerobicHighTargetMax')),
        'anaerobic': _safe_float(be.get('monthlyLoadAnaerobic'),1),
        'anaerobic_target_min': _safe_int(be.get('monthlyLoadAnaerobicTargetMin')),
        'anaerobic_target_max': _safe_int(be.get('monthlyLoadAnaerobicTargetMax'))
    }
    monthly = {k:v for k,v in monthly.items() if v is not None}
    if monthly:
        result['monthly_load_balance'] = monthly
    vo2 = raw.get('mostRecentVO2Max',{}) or {}
    generic = vo2.get('generic',{}) if isinstance(vo2.get('generic'),dict) else {}
    value = _safe_float(_deep_get(generic,['vo2MaxValue','vo2MaxPreciseValue','vo2Max']))
    status = generic.get('vo2MaxStatus') or generic.get('fitnessLevel') or generic.get('vo2MaxCategory') or generic.get('category') or _deep_get(vo2,['vo2MaxStatus','fitnessLevel'])
    if value is not None or status:
        result['vo2_max'] = {'value':value,'status':humanize_enum(status) if isinstance(status,str) else status}
        result['vo2_max'] = {k:v for k,v in result['vo2_max'].items() if v is not None}
    heat = vo2.get('heatAltitudeAcclimation',{}) or raw.get('heatAltitudeAcclimation',{}) or {}
    hp = heat.get('heatAcclimationPercentage'); ht = heat.get('heatTrend'); ap = heat.get('altitudeAcclimationPercentage') or heat.get('acclimationPercentage'); at = heat.get('altitudeTrend')
    if hp is not None or ht:
        result['heat_acclimation'] = {'percentage':_safe_int(hp),'trend':humanize_enum(ht) if isinstance(ht,str) else ht}
    if ap is not None or at:
        result['altitude_acclimation'] = {'percentage':_safe_int(ap),'trend':humanize_enum(at) if isinstance(at,str) else at}
    return {k:v for k,v in result.items() if v is not None}


def _find_first_key(obj, keys):
    """Recursively find the first non-null value for any key."""
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] is not None and obj[key] != "":
                return obj[key]
        for value in obj.values():
            found = _find_first_key(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_first_key(value, keys)
            if found is not None:
                return found
    return None


def get_recovery_time_hours(api, target_date_str, training_status_raw=None):
    """Return Garmin recovery time in hours."""
    readiness = None
    try:
        readiness = api.get_training_readiness(target_date_str)
    except Exception as e:
        print(f'[training_readiness] Warning: {e}', file=sys.stderr)

    recovery_minutes = _find_first_key(readiness, ('recoveryTime', 'recovery_time'))
    if recovery_minutes is not None:
        value = _safe_float(recovery_minutes, 1)
        if value is not None:
            return round(value / 60.0, 1)

    recovery_hours = _find_first_key(readiness, ('recoveryTimeHours', 'recovery_time_hours'))
    if recovery_hours is not None:
        return _safe_float(recovery_hours, 1)

    recovery_hours = _find_first_key(training_status_raw, ('recoveryTimeHours', 'recovery_time_hours'))
    if recovery_hours is not None:
        return _safe_float(recovery_hours, 1)

    recovery_minutes = _find_first_key(training_status_raw, ('recoveryTime', 'recovery_time'))
    if recovery_minutes is not None:
        value = _safe_float(recovery_minutes, 1)
        if value is not None:
            return round(value / 60.0, 1)
    return None


def _activity_sport(activity):
    raw = _deep_get(activity, ['activityType.typeKey','activityType','sport','sportType'], '') or ''
    raw = str(raw).lower()
    if 'run' in raw or 'jog' in raw:
        return 'running'
    if any(x in raw for x in ('cycl','bike','biking')):
        return 'cycling'
    if 'swim' in raw:
        return 'swimming'
    if 'multi' in raw or 'triathlon' in raw or 'duathlon' in raw or 'aquathlon' in raw:
        return 'multisport'
    if 'transition' in raw:
        return 'transition'
    return 'other'


def _activity_date(activity):
    value = activity.get('startTimeLocal') or activity.get('startTimeGMT') or activity.get('startTime') or ''
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return None


def _activity_duration_hours(activity):
    duration = activity.get('duration') or activity.get('elapsedDuration') or activity.get('movingDuration') or 0
    try:
        return float(duration) / 3600.0
    except (ValueError, TypeError):
        return 0.0


def _activity_distance_km(activity):
    try:
        return float(activity.get('distance') or 0) / 1000.0
    except (ValueError, TypeError):
        return 0.0


def _activity_load(activity):
    # Garmin has used several field names across devices/eras. Preserve only
    # values actually supplied by Garmin; never estimate load from distance.
    value = _deep_get(activity, [
        'activityTrainingLoad', 'trainingLoad', 'exerciseLoad',
        'activityTrainingLoadDTO.trainingLoad', 'summaryDTO.trainingLoad',
        'summaryDTO.exerciseLoad', 'activityTrainingLoadDTO.exerciseLoad'
    ])
    return _safe_float(value, 1)


def _empty_sport_totals():
    return {
        'activity_count': 0,
        'distance_km': 0.0,
        'duration_hours': 0.0,
        'exercise_load': 0.0,
        'exercise_load_available': False
    }


def _aggregate_activities(activities):
    sports = {s:_empty_sport_totals() for s in ('running','cycling','swimming','multisport','other','transition')}
    total = _empty_sport_totals()
    for activity in activities:
        sport = _activity_sport(activity)
        if sport == 'multisport':
            # The parent multisport summary is retained for classification but
            # its distance/duration should not be added when child legs exist,
            # otherwise the workout is double-counted.
            continue
        bucket = sports.setdefault(sport, _empty_sport_totals())
        dist = _activity_distance_km(activity)
        hours = _activity_duration_hours(activity)
        load = _activity_load(activity)
        bucket['activity_count'] += 1
        bucket['distance_km'] += dist
        bucket['duration_hours'] += hours
        total['activity_count'] += 1
        total['distance_km'] += dist
        total['duration_hours'] += hours
        if load is not None:
            bucket['exercise_load'] += load
            bucket['exercise_load_available'] = True
            total['exercise_load'] += load
            total['exercise_load_available'] = True
    for bucket in list(sports.values()) + [total]:
        bucket['distance_km'] = round(bucket['distance_km'],2)
        bucket['duration_hours'] = round(bucket['duration_hours'],2)
        if not bucket['exercise_load_available']:
            bucket.pop('exercise_load',None)
            bucket.pop('exercise_load_available',None)
        else:
            bucket['exercise_load'] = round(bucket['exercise_load'],1)
            bucket.pop('exercise_load_available',None)
    return sports, total


def get_metric_trend(api, target_date, days=14, interval=1):
    """Return health plus sport-aware training trends.

    The historical trend is intentionally NOT run-only. Garmin's training-load
    model is based on physiological impact across recorded activities, while
    running distance remains a separate sport-specific metric. We therefore
    expose both running volume and total endurance volume by sport.
    """
    from garmin_to_json import get_health_stats
    if days <= 0:
        return []

    trend = []
    # interval=1 => daily windows; interval=7 => non-overlapping weekly windows
    if interval == 1:
        windows = [(target_date - timedelta(days=i), target_date - timedelta(days=i)) for i in reversed(range(days))]
    else:
        windows = []
        end = target_date
        remaining = days
        while remaining > 0:
            window_days = min(interval, remaining)
            start = end - timedelta(days=window_days-1)
            windows.append((start, end))
            end = start - timedelta(days=1)
            remaining -= window_days
        windows.reverse()

    for start_date, end_date in windows:
        ds = end_date.isoformat()
        try:
            health = get_health_stats(api, ds)
        except Exception:
            health = {}
        try:
            status = get_training_status_details(api, ds)
        except Exception:
            status = {}
        try:
            activities = api.get_activities_by_date(start_date.isoformat(), end_date.isoformat())
        except Exception as e:
            print(f'[trend_activities] Warning {start_date}..{end_date}: {e}', file=sys.stderr)
            activities = []

        sports, total = _aggregate_activities(activities if isinstance(activities,list) else [])
        entry = {
            'date': ds,
            'window_start': start_date.isoformat(),
            'window_end': end_date.isoformat(),
            'window_days': (end_date-start_date).days+1,
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
            'sport_volume': {
                sport: {
                    'activity_count': values['activity_count'],
                    'distance_km': values['distance_km'],
                    'duration_hours': values['duration_hours'],
                    **({'exercise_load': values['exercise_load']} if 'exercise_load' in values else {})
                }
                for sport, values in sports.items()
                if values['activity_count'] > 0
            },
        }
        if total.get('exercise_load') is not None:
            entry['total_exercise_load'] = total['exercise_load']
        trend.append({k:v for k,v in entry.items() if v is not None})
    return trend


def get_body_battery_trend(api,target_date,days=7):
    start=target_date-timedelta(days=days-1)
    try: data=api.get_body_battery(start.isoformat(),target_date.isoformat())
    except Exception as e: print(f'[body_battery] Warning: {e}',file=sys.stderr); return []
    out=[]
    for day in data if isinstance(data,list) else []:
        if not isinstance(day,dict): continue
        vals=day.get('bodyBatteryValuesArray') or []; levels=[v[1] for v in vals if isinstance(v,(list,tuple)) and len(v)>1 and v[1] is not None]
        obj={'date':day.get('date') or day.get('calendarDate'),'charged':_safe_int(day.get('charged')),'drained':_safe_int(day.get('drained')),'high':max(levels) if levels else None,'low':min(levels) if levels else None}
        out.append({k:v for k,v in obj.items() if v is not None})
    return out


def get_activity_splits(api,activity_id,activity_type='run'):
    from garmin_to_json import format_pace
    try: splits=api.get_activity_splits(activity_id)
    except Exception: splits={}
    laps=splits.get('lapDTOs',[]) if isinstance(splits,dict) else []; out=[]; cumulative=0.0
    for lap in laps:
        dist=lap.get('distance',0) or 0; dur=lap.get('duration',0) or lap.get('elapsedDuration',0) or 0; cumulative+=dur
        raw_stride=_safe_float(lap.get('strideLength') or lap.get('avgStrideLength')); stride=round(raw_stride/100,4) if raw_stride and raw_stride>3 else raw_stride
        raw_vo=_safe_float(lap.get('verticalOscillation') or lap.get('avgVerticalOscillation')); vo=round(raw_vo/10,2) if raw_vo and raw_vo>20 else raw_vo
        max_speed=lap.get('maxSpeed') or lap.get('maximumSpeed'); best=None
        if max_speed and max_speed>0:
            sec=1000/float(max_speed); best=f'{int(sec//60)}:{int(round(sec%60)):02d}'
        obj={'lap':_safe_int(lap.get('lapIndex') or lap.get('splitIndex') or lap.get('lap')),'distance_km':round(dist/1000,3),'time_min':round(dur/60,2),'cumulative_time_min':round(cumulative/60,2),'moving_time_min':round((lap.get('movingDuration') or dur)/60,2),'avg_pace':format_pace(dist,dur,activity_type),'avg_moving_pace':format_pace(dist,lap.get('movingDuration') or dur,activity_type),'best_pace':best,'avg_hr':_safe_int(lap.get('averageHR') or lap.get('avgHR')),'max_hr':_safe_int(lap.get('maxHR') or lap.get('maximumHR')),'calories':_safe_int(lap.get('calories')),'avg_power_w':_safe_int(lap.get('averagePower') or lap.get('avgPower') or lap.get('power')),'normalized_power_w':_safe_int(lap.get('normalizedPower') or lap.get('normPower') or lap.get('averagePower') or lap.get('avgPower')),'cadence_spm':_safe_int(lap.get('averageRunCadence') or lap.get('avgRunCadence') or lap.get('cadence') or lap.get('avgCadence')),'max_cadence_spm':_safe_int(lap.get('maxRunCadence') or lap.get('maximumRunCadence') or lap.get('maxCadence')),'avg_gct_ms':_safe_float(lap.get('groundContactTime') or lap.get('avgGroundContactTime') or lap.get('gct'),1),'avg_stride_length_m':stride,'vertical_oscillation_cm':vo,'vertical_ratio_pct':_safe_float(lap.get('verticalRatio') or lap.get('avgVerticalRatio') or lap.get('vertRatio'),2),'elevation_gain_m':_safe_float(lap.get('elevationGain') or lap.get('sumElevationGain') or lap.get('ascent'),1),'elevation_loss_m':_safe_float(lap.get('elevationLoss') or lap.get('sumElevationLoss') or lap.get('descent'),1),'intensityType':lap.get('intensityType') or lap.get('stepType')}
        out.append({k:v for k,v in obj.items() if v is not None})
    return out


def _is_multisport(t):
    t=(t or '').lower(); return 'multi_sport' in t or 'multisport' in t


def _child_ids(api,parent):
    try: detail=api.get_activity(parent)
    except Exception: return []
    meta=detail.get('metadataDTO',{}) if isinstance(detail,dict) else {}
    ids=meta.get('childIds') or meta.get('childActivityIds') or detail.get('childIds') or detail.get('childActivityIds') or []
    if isinstance(ids,dict): ids=list(ids.values())
    return [x for x in ids if x]


def _child_summary(api,child_id):
    from garmin_to_json import format_pace
    try: detail=api.get_activity(child_id)
    except Exception: detail={}
    summary=detail.get('summaryDTO',{}) if isinstance(detail.get('summaryDTO'),dict) else {}; typ=_deep_get(detail,['activityTypeDTO.typeKey','activityType.typeKey','activityType'],''); dist=summary.get('distance') or detail.get('distance') or 0; dur=summary.get('duration') or detail.get('duration') or 0
    load=_deep_get(summary,['trainingLoad','exerciseLoad']) or _deep_get(detail,['trainingLoad','exerciseLoad','activityTrainingLoad'])
    return {'activityId':child_id,'name':detail.get('activityName') or typ or 'Leg','type':typ,'distance_km':round(dist/1000,2) if dist else 0,'duration_mins':round(dur/60,2) if dur else 0,'avg_pace':format_pace(dist,dur,typ),'average_hr':_safe_float(summary.get('averageHR') or detail.get('averageHR')),'max_hr':_safe_float(summary.get('maxHR') or detail.get('maxHR')),'aerobic_training_effect':_safe_float(summary.get('trainingEffect') or summary.get('aerobicTrainingEffect') or detail.get('aerobicTrainingEffect')),'anaerobic_training_effect':_safe_float(summary.get('anaerobicTrainingEffect') or detail.get('anaerobicTrainingEffect')),'exercise_load':_safe_float(load,1)}


def get_activities(api,target_date_str):
    try: acts=api.get_activities_by_date(target_date_str,target_date_str)
    except Exception: acts=[]
    from garmin_to_json import deep_get, format_pace
    out=[]
    for act in acts:
        aid=act.get('activityId'); typ=deep_get(act,['activityType.typeKey','activityType'],'')
        if _is_multisport(typ) and aid:
            ids=_child_ids(api,aid)
            if ids:
                transitions=0
                for cid in ids:
                    obj=_child_summary(api,cid)
                    if 'transition' in (obj.get('type') or '').lower(): transitions+=1; obj['name']=f'Transition {transitions} (T{transitions})'
                    splits=get_activity_splits(api,cid,obj.get('type'))
                    if splits: obj['activity_splits']=splits
                    obj['parentActivityId']=aid; out.append({k:v for k,v in obj.items() if v is not None})
                continue
        dist=act.get('distance',0) or 0; dur=act.get('duration',0) or 0
        load=_deep_get(act,['trainingLoad','exerciseLoad','activityTrainingLoad','summaryDTO.trainingLoad','summaryDTO.exerciseLoad'])
        obj={'activityId':aid,'name':act.get('activityName'),'type':typ,'distance_km':round(dist/1000,2) if dist else 0,'duration_mins':round(dur/60,2) if dur else 0,'avg_pace':format_pace(dist,dur,typ),'average_hr':_safe_float(act.get('averageHR') or act.get('avgHR')),'max_hr':_safe_float(act.get('maxHR') or act.get('maximumHR')),'aerobic_training_effect':_safe_float(act.get('aerobicTrainingEffect')),'anaerobic_training_effect':_safe_float(act.get('anaerobicTrainingEffect')),'exercise_load':_safe_float(load,1)}
        if aid:
            splits=get_activity_splits(api,aid,typ)
            if splits: obj['activity_splits']=splits
        out.append({k:v for k,v in obj.items() if v is not None})
    return out

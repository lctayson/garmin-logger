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


def _format_elapsed_time(seconds):
    if seconds is None:
        return None
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return None
    if total < 0:
        return None
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes}:{secs:02d}'


def get_activity_splits(api, activity_id, activity_type='run'):
    from garmin_to_json import format_pace
    try:
        splits = api.get_activity_splits(activity_id)
    except Exception:
        splits = {}
    laps = splits.get('lapDTOs', []) if isinstance(splits, dict) else []
    out = []
    cumulative = 0.0
    for lap in laps:
        dist = lap.get('distance', 0) or 0
        dur = lap.get('duration', 0) or lap.get('elapsedDuration', 0) or 0
        elapsed_dur = lap.get('elapsedDuration')
        cumulative += dur
        raw_stride = _safe_float(lap.get('strideLength') or lap.get('avgStrideLength'))
        stride = round(raw_stride / 100, 4) if raw_stride and raw_stride > 3 else raw_stride
        raw_vo = _safe_float(lap.get('verticalOscillation') or lap.get('avgVerticalOscillation'))
        vo = round(raw_vo / 10, 2) if raw_vo and raw_vo > 20 else raw_vo
        max_speed = lap.get('maxSpeed') or lap.get('maximumSpeed')
        best = None
        if max_speed and max_speed > 0:
            sec = 1000 / float(max_speed)
            best = f'{int(sec//60)}:{int(round(sec%60)):02d}'
        obj = {
            'lap': _safe_int(lap.get('lapIndex') or lap.get('splitIndex') or lap.get('lap')),
            'distance_km': round(dist / 1000, 3),
            'time_min': round(dur / 60, 2),
            'elapsed_time': _format_elapsed_time(elapsed_dur if elapsed_dur is not None else dur),
            'cumulative_time_min': round(cumulative / 60, 2),
            'moving_time_min': round((lap.get('movingDuration') or dur) / 60, 2),
            'avg_pace': format_pace(dist, dur, activity_type),
            'avg_moving_pace': format_pace(dist, lap.get('movingDuration') or dur, activity_type),
            'best_pace': best,
            'avg_hr': _safe_int(lap.get('averageHR') or lap.get('avgHR')),
            'max_hr': _safe_int(lap.get('maxHR') or lap.get('maximumHR')),
            'calories': _safe_int(lap.get('calories')),
            'avg_power_w': _safe_int(lap.get('averagePower') or lap.get('avgPower') or lap.get('power')),
            'normalized_power_w': _safe_int(lap.get('normalizedPower') or lap.get('normPower') or lap.get('averagePower') or lap.get('avgPower')),
            'cadence_spm': _safe_int(lap.get('averageRunCadence') or lap.get('avgRunCadence') or lap.get('cadence') or lap.get('avgCadence')),
            'max_cadence_spm': _safe_int(lap.get('maxRunCadence') or lap.get('maximumRunCadence') or lap.get('maxCadence')),
            'avg_gct_ms': _safe_float(lap.get('groundContactTime') or lap.get('avgGroundContactTime') or lap.get('gct'), 1),
            'avg_stride_length_m': stride,
            'vertical_oscillation_cm': vo,
            'vertical_ratio_pct': _safe_float(lap.get('verticalRatio') or lap.get('avgVerticalRatio') or lap.get('vertRatio'), 2),
            'elevation_gain_m': _safe_float(lap.get('elevationGain') or lap.get('sumElevationGain') or lap.get('ascent'), 1),
            'elevation_loss_m': _safe_float(lap.get('elevationLoss') or lap.get('sumElevationLoss') or lap.get('descent'), 1),
            'intensityType': lap.get('intensityType') or lap.get('stepType')
        }
        out.append({k: v for k, v in obj.items() if v is not None})
    return out

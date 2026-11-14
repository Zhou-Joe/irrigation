"""Versioned hourly ET0 approximation, calibrated against the supplied Maxicom report.

This is not Rain Bird's verified proprietary algorithm. Inputs are the existing
normalized Celsius / percent / Ly / km hourly observations. Results are derived
at read time; source observations and irrigation decisions are never rewritten.
FAO equations: https://www.fao.org/4/X0490E/x0490e08.htm (hourly Eq. 53).
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MODEL_VERSION = 'maxicom-hourly-estimate-v1'
MODEL_LABEL = 'ET₀估算（小时近似复算）'
SHANGHAI = ZoneInfo('Asia/Shanghai')
LY_MJ_M2 = 0.041868
SOURCE_NOTE = ('ET₀ 为逐小时近似复算值，非 Maxicom 原厂值或灌溉补水量。'
               '与样表271个完整日对照，平均绝对差约0.13 mm/天，7–9月约0.17 mm/天；'
               '缺少完整24小时或必要参数时留空。')

# The calibration retained the source WETHR_CF station-31 latitude (40 degrees).
# Longitude, elevation and wind height below are explicit approximation inputs,
# not newly verified station measurements. Never apply this profile to other sites.
DEFAULT_STATION_PROFILES = {
    31: {'latitude': 40.0, 'longitude': 121.655407, 'elevation_m': 10.0021,
         'wind_height_m': 2.0,
         'note': '纬度40°沿用原站点配置，与项目地图约31.15°有差异，待核对；'
                 '经度121.655407°、海拔10m及测风高度2m为本次复算参数。'}
}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def profile_for_station(index):
    from django.conf import settings
    profiles = getattr(settings, 'MAXICOM_ET0_STATION_PROFILES', DEFAULT_STATION_PROFILES)
    if not isinstance(profiles, dict):
        return None
    profile = profiles.get(index, profiles.get(str(index)))
    if not isinstance(profile, dict):
        return None
    limits = {'latitude': (-89, 89), 'longitude': (-180, 180),
              'elevation_m': (-500, 9000), 'wind_height_m': (0.2, 100)}
    result = {}
    for key, (low, high) in limits.items():
        value = _number(profile.get(key))
        if value is None or not low <= value <= high:
            return None
        result[key] = value
    result['note'] = str(profile.get('note', ''))
    result['model_version'] = MODEL_VERSION
    return result


def _saturation(temperature):
    return 0.6108 * math.exp(17.27 * temperature / (temperature + 237.3))


def _reference_et(temperature, humidity, wind, net_radiation, pressure, soil_heat=0):
    saturation = _saturation(temperature)
    actual = saturation * humidity / 100
    slope = 4098 * saturation / (temperature + 237.3) ** 2
    gamma = 0.000665 * pressure
    return (0.408 * slope * (net_radiation - soil_heat)
            + gamma * 37 / (temperature + 273) * wind * max(0, saturation - actual)
            ) / (slope + gamma * (1 + 0.34 * wind))


def _sun(stamp, latitude, longitude):
    # Calibration uses the midpoint half an hour before each raw hourly label.
    moment = stamp - timedelta(minutes=30)
    day = moment.timetuple().tm_yday
    phi = math.radians(latitude)
    distance = 1 + 0.033 * math.cos(2 * math.pi * day / 365)
    declination = 0.409 * math.sin(2 * math.pi * day / 365 - 1.39)
    seasonal = 2 * math.pi * (day - 81) / 364
    correction = (0.1645 * math.sin(2 * seasonal) - 0.1255 * math.cos(seasonal)
                  - 0.025 * math.sin(seasonal))
    hour = moment.hour + moment.minute / 60 + moment.second / 3600
    angle = math.pi / 12 * (hour + (longitude - 120) / 15 + correction - 12)
    sunset = math.acos(max(-1, min(1, -math.tan(phi) * math.tan(declination))))
    first = max(-sunset, angle - math.pi / 24)
    last = min(sunset, angle + math.pi / 24)
    radiation = 0 if first >= last else 12 * 60 / math.pi * 0.0820 * distance * (
        (last - first) * math.sin(phi) * math.sin(declination)
        + math.cos(phi) * math.cos(declination) * (math.sin(last) - math.sin(first)))
    return max(0, radiation), angle, sunset


def estimate_days(rows, profile):
    """Calculate each complete local day; preceding-day rows warm the cloud estimate.

    A missing/invalid hour or ambiguous duplicate leaves that day's ET0 unavailable.
    No daily default, monthly ET or rainfall is substituted into the calculation.
    """
    if profile is None:
        return {}
    elevation = profile['elevation_m']
    pressure = 101.3 * ((293 - 0.0065 * elevation) / 293) ** 5.26
    wind_adjust = 4.87 / math.log(67.8 * profile['wind_height_m'] - 5.42)
    days = defaultdict(lambda: {'hours': set(), 'values': [], 'errors': set()})
    cloud = cloud_stamp = None
    for row in sorted(rows, key=lambda item: item['timestamp']):
        stamp = datetime.strptime(row['timestamp'], '%Y%m%d%H%M%S').replace(
            tzinfo=timezone.utc).astimezone(SHANGHAI)
        record = days[stamp.date()]
        if stamp.minute or stamp.second or stamp.hour in record['hours']:
            record['errors'].add('小时记录重复或不在整点')
        record['hours'].add(stamp.hour)
        temp, humidity, solar, wind = [_number(row.get(key)) for key in
                                      ('temperature', 'humidity', 'solar_radiation', 'wind_run')]
        if (None in (temp, humidity, solar, wind) or not -85 <= temp <= 80
                or not 0 <= humidity <= 100 or solar < 0 or wind < 0):
            record['errors'].add('小时温湿度、光照或风程缺失/无效')
            continue
        measured = solar * LY_MJ_M2
        extraterrestrial, angle, sunset = _sun(stamp, profile['latitude'], profile['longitude'])
        clear_sky = (0.75 + 2e-5 * elevation) * extraterrestrial
        if extraterrestrial > 0.2:
            ratio = measured / clear_sky
            if sunset - 0.79 <= angle <= sunset - 0.52:
                cloud, cloud_stamp = ratio, stamp
        elif cloud is not None and stamp - cloud_stamp <= timedelta(hours=18):
            ratio = cloud
        else:
            record['errors'].add('前一日云量观测不足')
            continue
        # Version-1 calibration choices: G=0; cloud ratio [0,1]; u2>=0.5;
        # negative hourly ET clips to zero. These are disclosed approximation
        # parameters, not a claim about the original Rain Bird implementation.
        ratio = max(0, min(1, ratio))
        actual = _saturation(temp) * humidity / 100
        longwave = (4.903e-9 / 24 * (temp + 273.16) ** 4
                    * (0.34 - 0.14 * math.sqrt(actual)) * (1.35 * ratio - 0.35))
        net = 0.77 * measured - longwave
        speed = max(0.5, wind * 1000 / 3600 * wind_adjust)
        value = max(0, _reference_et(temp, humidity, speed, net, pressure))
        if not math.isfinite(value):
            record['errors'].add('复算结果无效')
            continue
        record['values'].append(value)
    result = {}
    for day, record in days.items():
        if len(record['hours']) != 24:
            record['errors'].add('未满24小时')
        complete = not record['errors'] and len(record['values']) == 24
        result[day] = {'et': sum(record['values']) if complete else None,
                       'et_source': 'estimated' if complete else 'unavailable',
                       'et_method': MODEL_VERSION, 'et_valid_hours': len(record['values']),
                       'et_note': 'ET₀估算值' if complete else 'ET₀留空：' + '、'.join(sorted(record['errors']))}
    return result

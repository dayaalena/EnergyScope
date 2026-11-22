"""Контроль измерений, единая часовая шкала UTC и признаки без будущего."""
import numpy as np
import pandas as pd

WEATHER = ['temperature', 'humidity', 'precipitation', 'wind']


def prepare(energy, weather):
    energy = energy.copy()
    energy['time'] = pd.to_datetime(energy['startTime'], utc=True, errors='coerce')
    energy['published'] = pd.to_datetime(energy['publishTime'], utc=True, errors='coerce')
    energy['demand'] = pd.to_numeric(energy['initialDemandOutturn'], errors='coerce')
    raw_n = len(energy)
    bad_time = int(energy['time'].isna().sum())
    invalid = energy['demand'].le(0) | ~np.isfinite(energy['demand'])
    energy.loc[invalid, 'demand'] = np.nan
    duplicates = int(energy.duplicated('time', keep=False).sum())
    # При нескольких публикациях выбирается последняя; это пересмотренный архив.
    energy = energy.dropna(subset=['time']).sort_values('published').drop_duplicates('time', keep='last')
    half = energy.set_index('time').sort_index()
    expected = pd.date_range(half.index.min(), half.index.max(), freq='30min', tz='UTC')
    missing_half = len(expected.difference(half.index))
    hourly = half['demand'].resample('h').agg(['mean', 'count']).rename(columns={'mean': 'y', 'count': 'valid_halfhours'})
    hourly.loc[hourly['valid_halfhours'].ne(2), 'y'] = np.nan
    hourly['publish_time'] = half['published'].resample('h').max()
    weather = weather.copy()
    weather['time'] = pd.to_datetime(weather['time'], utc=True, errors='coerce')
    weather_duplicates = int(weather.duplicated('time').sum())
    weather = weather.dropna(subset=['time']).drop_duplicates('time', keep='last').set_index('time').sort_index()
    for name in WEATHER:
        weather[name] = pd.to_numeric(weather[name], errors='coerce')
    weather.loc[~weather['temperature'].between(-60, 60), 'temperature'] = np.nan
    weather.loc[~weather['humidity'].between(0, 100), 'humidity'] = np.nan
    for name in ['precipitation', 'wind']:
        weather.loc[weather[name].lt(0), name] = np.nan
    result = hourly.join(weather[WEATHER])
    result.index.name = 'time'
    quality = {'raw_energy_rows': raw_n, 'invalid_time_rows': bad_time,
               'duplicate_energy_rows': duplicates, 'invalid_energy_rows': int(invalid.sum()),
               'missing_halfhours': missing_half, 'hours': len(result),
               'valid_hours': int(result['y'].notna().sum()),
               'missing_hours': int(result['y'].isna().sum()),
               'completeness_percent': round(100 * result['y'].notna().mean(), 3),
               'weather_duplicate_rows': weather_duplicates,
               'weather_missing_hours': {c: int(result[c].isna().sum()) for c in WEATHER},
               'weather_last_time': str(weather.index.max()),
               'first_time': str(result.index.min()), 'last_time': str(result.index.max())}
    return result, quality


def build_features(frame, config, future_index=None):
    if config['weather_lag_hours'] < config['weather_delay_days'] * 24 + config['horizon_hours']:
        raise ValueError('Погодный лаг слишком короткий для горизонта и задержки источника')
    last = max(frame.index.max(), future_index.max()) if future_index is not None else frame.index.max()
    idx = pd.date_range(frame.index.min(), last, freq='h', tz='UTC', name='time')
    raw = frame.reindex(idx)
    local = idx.tz_convert('Europe/London')
    x = pd.DataFrame(index=idx)
    x['hour_sin'] = np.sin(2 * np.pi * local.hour / 24)
    x['hour_cos'] = np.cos(2 * np.pi * local.hour / 24)
    x['week_sin'] = np.sin(2 * np.pi * (local.dayofweek * 24 + local.hour) / 168)
    x['week_cos'] = np.cos(2 * np.pi * (local.dayofweek * 24 + local.hour) / 168)
    x['year_sin'] = np.sin(2 * np.pi * local.dayofyear / 365.25)
    x['year_cos'] = np.cos(2 * np.pi * local.dayofyear / 365.25)
    x['weekend'] = (local.dayofweek >= 5).astype(int)
    # 48 ч гарантируют, что весь суточный горизонт использует уже полученный факт.
    for lag in [48, 168, 336]:
        x[f'lag_{lag}'] = raw['y'].shift(lag)
    x['mean_prev_24'] = raw['y'].shift(48).rolling(24, min_periods=18).mean()
    x['std_prev_24'] = raw['y'].shift(48).rolling(24, min_periods=18).std()
    for name in WEATHER:
        x[f'{name}_proxy'] = raw[name].shift(config['weather_lag_hours'])
    return temperature_features(x)


def temperature_features(x):
    x = x.copy()
    x['heating_proxy'] = (18 - x['temperature_proxy']).clip(lower=0)
    x['cooling_proxy'] = (x['temperature_proxy'] - 22).clip(lower=0)
    return x

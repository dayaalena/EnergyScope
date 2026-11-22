"""Инкрементальный сбор JSON Elexon и CSV Open-Meteo без ключей API."""
import calendar
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from .storage import atomic_write, digest, log_event

ENERGY_API = 'https://data.elexon.co.uk/bmrs/api/v1/demand/outturn/stream'
WEATHER_API = 'https://archive-api.open-meteo.com/v1/archive'


def fetch(root, source, url, path, config):
    """Не сохраняет повреждённый ответ; кеш остаётся пригодным после ошибки."""
    for attempt in range(1, config['request_attempts'] + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'EnergyScope academic project/1.0'})
            with urllib.request.urlopen(req, timeout=config['request_timeout_seconds']) as r:
                raw = r.read()
            if source == 'elexon':
                value = json.loads(raw)
                if not isinstance(value, list) or not value:
                    raise ValueError('Источник не вернул наблюдений')
                if not all('startTime' in row and 'initialDemandOutturn' in row for row in value):
                    raise ValueError('Изменилась структура ответа Elexon')
            elif b'\ntime,' not in raw:
                raise ValueError('Источник не вернул CSV с временной шкалой')
            atomic_write(path, raw)
            log_event(root, source, 'downloaded', url=url, file=str(path.relative_to(root)),
                      bytes=len(raw), sha256=digest(raw), attempt=attempt)
            return
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            log_event(root, source, 'retry' if attempt < config['request_attempts'] else 'error',
                      attempt=attempt, error=str(exc), url=url)
            if attempt == config['request_attempts']:
                raise RuntimeError(f'Не удалось получить {source}: {exc}') from exc
            time.sleep(min(2 ** (attempt - 1), 4))


def cached_end(paths, source):
    dates = []
    for path in paths:
        part = path.stem.split('_')[-1]
        try:
            dates.append(pd.Timestamp(part, tz='UTC'))
        except ValueError:
            pass
    return max(dates) if dates else None


def acquire(root, config, offline=False):
    """Загружаются только ещё не полученные полные дни; история не перекачивается."""
    root = Path(root)
    energy_dir = root / 'data' / 'raw' / 'elexon'
    weather_dir = root / 'data' / 'raw' / 'open_meteo'
    energy_dir.mkdir(parents=True, exist_ok=True)
    weather_dir.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(config['start_date'], tz='UTC').normalize()
    now = pd.Timestamp.now(tz='UTC')
    end = pd.Timestamp(config['end_date'], tz='UTC') if config['end_date'] else now.normalize() - pd.Timedelta(days=1)
    if end >= now.normalize():
        raise ValueError('end_date должен быть завершившимся днём')
    # ERA5 обновляется с задержкой; семидневный буфер задаётся в конфигурации.
    weather_end = min(end, now.normalize() - pd.Timedelta(days=config['weather_delay_days']))
    issues = []
    for source, folder, finish in [('elexon', energy_dir, end), ('open_meteo', weather_dir, weather_end)]:
        paths = sorted(folder.glob('*.*'))
        last = cached_end(paths, source)
        first = max(start, last + pd.Timedelta(days=1)) if last is not None else start
        if offline:
            if not paths:
                raise FileNotFoundError(f'Нет сохранённых данных {source}. Запусти сбор с интернетом.')
            log_event(root, source, 'offline', files=len(paths))
            continue
        if first > finish:
            log_event(root, source, 'up_to_date', last_date=str(last.date()) if last is not None else None)
        while first <= finish:
            month_end = first.replace(day=calendar.monthrange(first.year, first.month)[1])
            stop = min(month_end, finish)
            if source == 'elexon':
                params = {'settlementDateFrom': str(first.date()), 'settlementDateTo': str(stop.date())}
                url = ENERGY_API + '?' + urllib.parse.urlencode(params)
                suffix = 'json'
            else:
                params = {'latitude': config['latitude'], 'longitude': config['longitude'],
                          'start_date': str(first.date()), 'end_date': str(stop.date()),
                          'hourly': 'temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m',
                          'timezone': 'UTC', 'models': 'era5', 'format': 'csv'}
                url = WEATHER_API + '?' + urllib.parse.urlencode(params)
                suffix = 'csv'
            path = folder / f'{source}_{first.date()}_{stop.date()}.{suffix}'
            try:
                fetch(root, source, url, path, config)
            except RuntimeError as exc:
                if not list(folder.glob('*.*')):
                    raise
                issues.append(str(exc))
                break
            first = stop + pd.Timedelta(days=1)
    return issues


def read_energy(root):
    rows = []
    for path in sorted((Path(root) / 'data/raw/elexon').glob('*.json')):
        rows.extend(json.loads(path.read_text(encoding='utf-8')))
    if not rows:
        raise ValueError('Нет данных энергопотребления')
    return pd.DataFrame(rows)


def read_weather(root):
    frames = []
    for path in sorted((Path(root) / 'data/raw/open_meteo').glob('*.csv')):
        text = path.read_text(encoding='utf-8')
        offset = text.index('\ntime,') + 1
        table = pd.read_csv(io.StringIO(text[offset:]))
        table.columns = ['time', 'temperature', 'humidity', 'precipitation', 'wind']
        frames.append(table)
    if not frames:
        raise ValueError('Нет погодных данных')
    return pd.concat(frames, ignore_index=True)

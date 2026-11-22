"""SQLite, атомарная запись результатов и журнал получения данных."""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
    os.replace(temp, path)


def save_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def log_event(root, source, status, **extra):
    item = {'time_utc': datetime.now(timezone.utc).isoformat(),
            'source': source, 'status': status, **extra}
    path = Path(root) / 'data' / 'loads.jsonl'
    path.parent.mkdir(exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(item, ensure_ascii=False) + '\n')


def digest(content):
    return hashlib.sha256(content).hexdigest()


def write_hourly(root, frame):
    """Первичный ключ исключает дубли; обновляется только изменившаяся строка."""
    cols = ['time', 'y', 'temperature', 'humidity', 'precipitation', 'wind',
            'valid_halfhours', 'publish_time']
    records = frame.reset_index().copy()
    records['time'] = records['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    records['publish_time'] = records['publish_time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    records = records[cols].astype(object).where(records[cols].notna(), None)
    with sqlite3.connect(Path(root) / 'data' / 'energy.sqlite') as db:
        db.execute('''CREATE TABLE IF NOT EXISTS hourly (
          time TEXT PRIMARY KEY, y REAL, temperature REAL, humidity REAL,
          precipitation REAL, wind REAL, valid_halfhours INTEGER, publish_time TEXT)''')
        changes = ','.join(f'{c}=excluded.{c}' for c in cols[1:])
        differs = ' OR '.join(f'hourly.{c} IS NOT excluded.{c}' for c in cols[1:])
        db.executemany(f'INSERT INTO hourly VALUES ({",".join("?" for _ in cols)}) '
                       f'ON CONFLICT(time) DO UPDATE SET {changes} WHERE {differs}',
                       list(records.itertuples(index=False, name=None)))
        changed = db.total_changes
    return changed

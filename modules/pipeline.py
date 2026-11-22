"""Единый вычислительный маршрут, используемый из CLI и GUI."""
import json
import pickle
import time
from pathlib import Path
import numpy as np
import pandas as pd

from . import analysis, ingestion, models, processing, visualization
from .storage import atomic_write, save_json, write_hourly


def csv_write(path, table, index=False):
    atomic_write(path, table.to_csv(index=index).encode('utf-8-sig'))


def run(root, config, offline=False, progress=lambda msg: print(msg, flush=True)):
    root = Path(root)
    (root / 'results').mkdir(exist_ok=True)
    started = time.perf_counter()
    progress('Получение новых данных' if not offline else 'Чтение сохранённых данных')
    issues = ingestion.acquire(root, config, offline)
    frame, quality = processing.prepare(ingestion.read_energy(root), ingestion.read_weather(root))
    changed = write_hourly(root, frame)
    csv_write(root/'results/hourly.csv', frame, index=True)
    stats, anomalies = analysis.describe(frame)
    csv_write(root/'results/anomalies.csv', anomalies, index=True)
    progress('Разведочный анализ завершён')
    best, widths, pred, folds, summary = models.compare(frame, config, progress)
    snapshot_path = root/'results/current.json'
    # Офлайн-пересчёт воспроизводит сохранённую точку прогноза, а не сдвигает её.
    if offline and snapshot_path.exists():
        origin = pd.Timestamp(json.loads(snapshot_path.read_text())['forecast_origin'])
    else:
        origin = pd.Timestamp.now(tz='UTC').ceil('h')
    progress('Построение итогового прогноза')
    forecast, fitted, x, train_n = models.future_forecasts(frame, config, origin, widths)
    scenario_model = 'ridge'
    scenario = models.scenarios(fitted[scenario_model], x, scenario_model, widths[scenario_model], config)
    train_start = origin - pd.Timedelta(days=config['train_days'])
    feature_history = processing.build_features(frame, config)
    eligible = feature_history.loc[(feature_history.index >= train_start) & (feature_history.index < origin), 'temperature_proxy'].dropna()
    scenario_range = [float(eligible.min()), float(eligible.max())]
    diagnostics = analysis.residual_diagnostics(pred, best)
    insights = analysis.conclusions(frame, forecast, stats, quality, best, summary)
    csv_write(root/'results/backtest_predictions.csv', pred)
    csv_write(root/'results/fold_metrics.csv', folds)
    csv_write(root/'results/model_metrics.csv', pd.DataFrame(summary))
    csv_write(root/'results/forecast.csv', forecast)
    csv_write(root/'results/scenarios.csv', scenario)
    csv_write(root/'results/features.csv', feature_history, index=True)
    save_json(root/'results/quality.json', quality)
    save_json(root/'results/diagnostics.json', diagnostics)
    atomic_write(root/'data/scenario_model.pkl', pickle.dumps({'model': fitted[scenario_model], 'features': x,
                       'width': widths[scenario_model], 'range': scenario_range}))
    progress('Сохранение визуализаций')
    visualization.save_figures(root, frame, stats, pred, forecast, summary, best, diagnostics)
    series = frame[['y', 'temperature']].reset_index()
    series['time'] = series['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    series = json.loads(series.to_json(orient='records'))
    elapsed = time.perf_counter() - started
    out = {'project': 'EnergyScope', 'forecast_origin': str(origin), 'best_model': best,
           'names': models.NAMES, 'snapshot_utc': str(pd.Timestamp.now(tz='UTC')),
           'last_observation': str(frame['y'].last_valid_index()), 'quality': quality,
           'stats': stats, 'metrics': summary, 'diagnostics': diagnostics,
           'forecast': json.loads(forecast.to_json(orient='records')),
           'scenarios': json.loads(scenario.to_json(orient='records')),
           'backtest': json.loads(pred.to_json(orient='records')),
           'folds': json.loads(folds.to_json(orient='records')), 'insights': insights,
           'series': series, 'scenario_model': scenario_model, 'scenario_range': scenario_range,
           'issues': issues, 'train_n': train_n, 'sqlite_changed_rows': changed,
           'runtime_seconds': round(elapsed, 2), 'config': config}
    save_json(snapshot_path, out)
    progress(f'Готово. Лучшая модель по валидации: {models.NAMES[best]}. Время: {elapsed:.1f} с')
    return out

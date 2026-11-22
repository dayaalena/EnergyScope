"""Три модели, временная валидация, отдельная калибровка и тест."""
import math
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .processing import build_features, temperature_features

NAMES = {'seasonal_naive': 'Сезонный наивный', 'ridge': 'Ridge',
         'boosting': 'Градиентный бустинг'}


def metrics(actual, predicted):
    actual, predicted = np.asarray(actual, float), np.asarray(predicted, float)
    keep = np.isfinite(actual) & np.isfinite(predicted)
    if not keep.any():
        raise ValueError('Нет общих наблюдений для сравнения моделей')
    error = predicted[keep] - actual[keep]
    return {'MAE': float(np.abs(error).mean()), 'RMSE': float(np.sqrt(np.mean(error ** 2))),
            'n': int(keep.sum())}


def estimator(name, config):
    if name == 'ridge':
        return make_pipeline(SimpleImputer(strategy='median', add_indicator=True),
                             StandardScaler(), Ridge(alpha=10.0))
    if name == 'boosting':
        return make_pipeline(SimpleImputer(strategy='median', add_indicator=True),
                             HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=15,
                              min_samples_leaf=40, l2_regularization=1.0,
                              early_stopping=False, random_state=config['seed']))
    return None


def fit_at(frame, config, origin, selected=None):
    """Ни признаки, ни обучение не получают позднее опубликованных измерений."""
    horizon = config['horizon_hours']
    idx = pd.date_range(origin, periods=horizon, freq='h')
    past = frame.copy()
    past.loc[past['publish_time'].gt(origin) | past.index.to_series().ge(origin), 'y'] = np.nan
    x = build_features(past, config, idx)
    train = (x.index < origin) & (x.index >= origin - pd.Timedelta(days=config['train_days']))
    y = past['y'].reindex(x.index)
    # Тестируемые алгоритмы обучаются на одних и тех же строках.
    train &= y.notna() & x['lag_336'].notna() & x['temperature_proxy'].notna()
    if int(train.sum()) < 24 * 90:
        raise ValueError('Нужно не менее 90 дней пригодной истории для обучения')
    future = x.loc[idx].copy()
    if future[['lag_168', 'lag_48', 'temperature_proxy']].isna().any().any():
        raise ValueError('Для горизонта нет обязательных лагов. Обнови данные или выбери сохранённый расчёт.')
    fitted, preds = {}, {}
    for name in selected or NAMES:
        model = estimator(name, config)
        if model is None:
            p = future['lag_168'].to_numpy()
        else:
            model.fit(x.loc[train], y.loc[train])
            p = np.maximum(0, model.predict(future))
        fitted[name] = model
        preds[name] = p
    return fitted, future, preds, int(train.sum())


def compare(frame, config, progress=lambda msg: None):
    total = sum(config[k] for k in ['validation_folds', 'calibration_folds', 'test_folds'])
    last = frame['y'].last_valid_index().normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=2)
    origins = pd.date_range(end=last, periods=total, freq=f'{config["fold_step_days"]}D')
    records, fold_metrics = [], []
    v, c = config['validation_folds'], config['calibration_folds']
    for i, origin in enumerate(origins):
        phase = 'validation' if i < v else 'calibration' if i < v+c else 'test'
        progress(f'Сравнение моделей: окно {i+1}/{total}, {origin.date()} ({phase})')
        _, x, preds, train_n = fit_at(frame, config, origin)
        actual = frame['y'].reindex(x.index).to_numpy()
        common = np.isfinite(actual)
        for p in preds.values():
            common &= np.isfinite(p)
        if common.sum() != config['horizon_hours']:
            raise ValueError(f'Неполное проверочное окно {origin}: {common.sum()} часов')
        for name, p in preds.items():
            fold_metrics.append({'phase': phase, 'origin': str(origin), 'model': name,
                                 'train_n': train_n, **metrics(actual, p)})
            for h, (t, a, b) in enumerate(zip(x.index, actual, p), 1):
                records.append({'phase': phase, 'origin': str(origin), 'time': str(t),
                                'horizon': h, 'model': name, 'actual': float(a),
                                'predicted': float(b), 'error': float(a-b)})
    predictions = pd.DataFrame(records)
    summary = []
    for (phase, name), group in predictions.groupby(['phase', 'model']):
        summary.append({'phase': phase, 'model': name, **metrics(group.actual, group.predicted)})
    validation = [r for r in summary if r['phase'] == 'validation']
    best = min(validation, key=lambda r: r['RMSE'])['model']
    # Непараметрический 90% интервал: отдельные калибровочные окна, без теста.
    widths = {}
    for name in NAMES:
        residuals = np.sort(np.abs(predictions.loc[(predictions.phase == 'calibration') & (predictions.model == name), 'error']))
        rank = min(len(residuals), math.ceil((len(residuals) + 1) * config['interval_level']))
        widths[name] = float(residuals[rank - 1])
    predictions['lower'] = [max(0, p-widths[m]) for p, m in zip(predictions.predicted, predictions.model)]
    predictions['upper'] = [p+widths[m] for p, m in zip(predictions.predicted, predictions.model)]
    for row in summary:
        group = predictions[(predictions.phase == row['phase']) & (predictions.model == row['model'])]
        row['coverage'] = float(((group.actual >= group.lower) & (group.actual <= group.upper)).mean())
        row['interval_halfwidth'] = widths[row['model']]
    return best, widths, predictions, pd.DataFrame(fold_metrics), summary


def future_forecasts(frame, config, origin, widths):
    fitted, x, preds, n = fit_at(frame, config, origin)
    records = []
    for name, p in preds.items():
        for h, (t, value) in enumerate(zip(x.index, p), 1):
            records.append({'time': str(t), 'horizon': h, 'model': name,
                            'predicted': float(value), 'lower': float(max(0, value-widths[name])),
                            'upper': float(value+widths[name])})
    return pd.DataFrame(records), fitted, x, n


def scenarios(model, x, name, width, config):
    """Меняется прогнозный температурный индикатор, а не фактическая погода."""
    rows = []
    for delta in [-3.0, 0.0, 3.0]:
        temp = x.copy()
        temp['temperature_proxy'] += delta
        temp = temperature_features(temp)
        p = temp['lag_168'].to_numpy() if model is None else np.maximum(0, model.predict(temp))
        for t, value in zip(x.index, p):
            rows.append({'time': str(t), 'delta': delta, 'model': name,
                         'predicted': float(value), 'lower': max(0.0, float(value-width)),
                         'upper': float(value+width)})
    return pd.DataFrame(rows)

"""Статистики, сезонные профили, аномалии и выводы по прозрачным правилам."""
import numpy as np
import pandas as pd

from .processing import WEATHER


def describe(frame):
    y = frame['y'].dropna()
    local = frame.index.tz_convert('Europe/London')
    # Порог оценивается только по прошлому году: не удаляем высокую нагрузку.
    history = frame['y'].shift(1).rolling(24 * 365, min_periods=24 * 90)
    q1, q3 = history.quantile(.25), history.quantile(.75)
    low, high = q1 - 3*(q3-q1), q3 + 3*(q3-q1)
    anomaly = (frame['y'] < low) | (frame['y'] > high)
    # Сезонные отклонения: сравниваем с тем же часом недели по прошлым неделям.
    seasonal = pd.concat([frame['y'].shift(168*k) for k in range(1, 9)], axis=1)
    center = seasonal.median(axis=1)
    mad = seasonal.sub(center, axis=0).abs().median(axis=1)
    relative = (frame['y'] - center).abs()
    seasonal_anomaly = (seasonal.count(axis=1) >= 6) & (relative > np.maximum(3 * 1.4826 * mad, center.abs() * .2))
    marked = frame.loc[anomaly | seasonal_anomaly, ['y']].copy()
    marked['reason'] = np.where(anomaly.loc[marked.index], 'За пределами 3 IQR', 'Отклонение от недельного профиля')
    table = frame[['y']].copy()
    table['hour'] = local.hour
    table['weekday'] = local.dayofweek
    table['month'] = local.month
    corr = frame[['y'] + WEATHER].corr()['y'].drop('y')
    monthly = frame['y'].resample('MS').mean()
    stats = {'mean_mw': float(y.mean()), 'std_mw': float(y.std()), 'min_mw': float(y.min()),
             'max_mw': float(y.max()), 'median_mw': float(y.median()),
             'anomaly_hours': len(marked), 'correlations': {k: float(v) for k,v in corr.items()},
             'hour_profile': table.groupby('hour').y.mean().to_dict(),
             'weekday_profile': table.groupby('weekday').y.mean().to_dict(),
             'month_profile': table.groupby('month').y.mean().to_dict(),
             'monthly': [{'time': str(t), 'y': float(v)} for t,v in monthly.dropna().items()],
             'lag24_correlation': float(frame['y'].corr(frame['y'].shift(24))),
             'lag168_correlation': float(frame['y'].corr(frame['y'].shift(168)))}
    return stats, marked


def residual_diagnostics(predictions, best):
    r = predictions[(predictions.phase == 'test') & (predictions.model == best)].copy()
    values = r.error.to_numpy()
    acf = []
    for lag in range(1, 13):
        a, b = [], []
        for _, group in r.groupby('origin'):
            e = group.sort_values('horizon').error.to_numpy()
            a.extend(e[:-lag]); b.extend(e[lag:])
        acf.append({'lag': lag, 'correlation': float(np.corrcoef(a,b)[0,1])})
    return {'mean_error_mw': float(values.mean()), 'std_error_mw': float(values.std(ddof=1)),
            'acf_within_window': acf, 'n': len(values)}


def conclusions(frame, forecast, stats, quality, best, summary):
    last = frame['y'].last_valid_index()
    recent = frame.loc[last-pd.Timedelta(hours=167):last, 'y'].mean()
    previous = frame.loc[last-pd.Timedelta(hours=335):last-pd.Timedelta(hours=168), 'y'].mean()
    change = float((recent/previous-1)*100)
    word = 'выросла' if change > 0 else 'снизилась' if change < 0 else 'не изменилась'
    chosen = forecast[forecast.model == best]
    prediction_change = float((chosen.predicted.mean()/recent-1)*100)
    test = next(r for r in summary if r['phase'] == 'test' and r['model'] == best)
    corr = stats['correlations']['temperature']
    return [
        f'Средняя нагрузка за последние 7 суток {word} на {abs(change):.1f}% относительно предыдущих 7 суток.',
        f'Корреляция нагрузки с температурой в Лондоне: {corr:.2f}. Это статистическая связь, её нельзя считать причинным влиянием.',
        f'Выделено {stats["anomaly_hours"]} часов с нетипичной нагрузкой. Наблюдения сохранены: высокая нагрузка сама по себе не является ошибкой.',
        f'Средняя прогнозная нагрузка на 24 часа отличается от средней за последние 7 суток на {prediction_change:+.1f}%. Сравнение не скорректировано по составу дней недели.',
        f'На независимом тесте RMSE выбранной модели: {test["RMSE"]:.0f} МВт; покрытие номинального 90% интервала: {test["coverage"]*100:.1f}%.',
        f'Полнота почасовой нагрузки: {quality["completeness_percent"]:.2f}%. Погода в Лондоне является приближённым индикатором условий Великобритании.'
    ]

"""Воспроизводимые графики для отчётов; данные GUI берутся из той же витрины."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .models import NAMES

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                     'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.grid': True, 'grid.alpha': .2, 'figure.dpi': 150})


def save_figures(root, frame, stats, predictions, forecast, summary, best, diagnostics):
    folder = Path(root) / 'results/figures'
    folder.mkdir(parents=True, exist_ok=True)
    def save(fig, name):
        fig.tight_layout(); fig.savefig(folder / name, bbox_inches='tight'); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9,3.2))
    frame['y'].resample('D').mean().plot(ax=ax, color='#276b8d', lw=.8)
    frame['y'].resample('D').mean().rolling(30).mean().plot(ax=ax, color='#c56a2b', lw=1.8)
    ax.set(xlabel='Дата UTC', ylabel='Нагрузка, МВт', title='Среднесуточная нагрузка и среднее за 30 суток')
    ax.legend(['Среднее за сутки', 'Среднее за 30 суток']); save(fig, 'trend.png')
    fig, axes = plt.subplots(1,3,figsize=(10,3.2))
    for ax,key,label in zip(axes,['hour_profile','weekday_profile','month_profile'],['Час местного времени','День недели от 0 до 6','Месяц']):
        v=stats[key];ax.plot(list(v),list(v.values()),marker='o',ms=3,color='#276b8d');ax.set(xlabel=label,ylabel='МВт')
    save(fig,'profiles.png')
    fig,ax=plt.subplots(figsize=(8,3.6))
    sample=frame[['temperature','y']].dropna().iloc[::12]
    ax.scatter(sample.temperature,sample.y,s=5,alpha=.3,color='#276b8d')
    ax.set(xlabel='Температура в Лондоне, °C',ylabel='Нагрузка, МВт',title='Связь температуры и нагрузки без причинной интерпретации');save(fig,'weather.png')
    fig,ax=plt.subplots(figsize=(8,3.6))
    test=[r for r in summary if r['phase']=='test']
    x=np.arange(len(test));ax.bar(x-.18,[r['MAE'] for r in test],.36,label='MAE',color='#276b8d')
    ax.bar(x+.18,[r['RMSE'] for r in test],.36,label='RMSE',color='#c56a2b')
    ax.set_xticks(x,[NAMES[r['model']] for r in test]);ax.set(ylabel='Ошибка, МВт',title='Независимые тестовые окна');ax.legend();save(fig,'metrics.png')
    fig,ax=plt.subplots(figsize=(9,3.5))
    p=predictions[(predictions.model==best)&(predictions.phase=='test')]
    p=p[p.origin==p.origin.max()].copy();t=__import__('pandas').to_datetime(p.time,utc=True)
    ax.fill_between(t,p.lower,p.upper,color='#d9e8ef',label='90% интервал')
    ax.plot(t,p.actual,color='#333333',label='Факт');ax.plot(t,p.predicted,color='#c56a2b',label='Прогноз')
    ax.set(xlabel='Время UTC',ylabel='МВт',title='Последнее независимое тестовое окно');ax.legend(ncol=3);save(fig,'test_forecast.png')
    fig,axes=plt.subplots(1,2,figsize=(9,3.2))
    p=predictions[(predictions.model==best)&(predictions.phase=='test')]
    axes[0].hist(p.error,bins=20,color='#276b8d');axes[0].set(xlabel='Факт − прогноз, МВт',ylabel='Число часов',title='Остатки на тесте')
    a=diagnostics['acf_within_window'];axes[1].bar([r['lag'] for r in a],[r['correlation'] for r in a],color='#276b8d');axes[1].set(xlabel='Лаг внутри окна, ч',ylabel='Корреляция',title='Зависимость остатков');save(fig,'residuals.png')
    fig,ax=plt.subplots(figsize=(8,3.3))
    for name,g in predictions[predictions.phase=='test'].groupby('model'):
        p=g.groupby('horizon').error.apply(lambda s:np.sqrt(np.mean(s**2)))
        ax.plot(p.index,p.values,label=NAMES[name])
    ax.set(xlabel='Горизонт, ч',ylabel='RMSE, МВт',title='Ошибка по горизонту');ax.legend();save(fig,'horizon.png')

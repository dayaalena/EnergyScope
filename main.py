"""Основной файл только конфигурирует и вызывает импортированные модули."""
import argparse
import json
import os
from pathlib import Path

# Ограничение потоков делает расчёт на обычном ноутбуке предсказуемым.
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')

from modules.gui import serve
from modules.pipeline import run


def main():
    parser = argparse.ArgumentParser(description='Анализ и прогнозирование нагрузки Великобритании')
    parser.add_argument('--run', action='store_true', help='Выполнить расчёт и завершиться')
    parser.add_argument('--offline', action='store_true', help='Использовать сохранённый снимок без интернета')
    parser.add_argument('--config', default='config.json', help='Путь к файлу конфигурации')
    parser.add_argument('--port', type=int, help='Порт локального интерфейса')
    parser.add_argument('--no-browser', action='store_true', help='Не открывать браузер автоматически')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    path = Path(args.config)
    if not path.is_absolute(): path = root/path
    config = json.loads(path.read_text(encoding='utf-8'))
    if config['horizon_hours'] != 24:
        parser.error('В этом проекте предусмотрен горизонт 24 часа')
    if args.run:
        run(root,config,args.offline)
    else:
        serve(root,config,args.port,args.offline,not args.no_browser)


if __name__ == '__main__':
    main()

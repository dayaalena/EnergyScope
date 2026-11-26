"""Локальный веб-интерфейс на стандартной библиотеке Python."""
import json
import pickle
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from .pipeline import run
from .processing import temperature_features


def serve(root, config, port=None, offline=False, open_browser=True):
    root = Path(root)
    state = {'running': False, 'message': 'Готово', 'error': None}
    lock = threading.Lock()

    def update():
        if not lock.acquire(blocking=False):
            return
        state.update(running=True, error=None)
        try:
            run(root, config, offline, lambda text: state.update(message=text))
        except Exception as exc:
            state.update(error=str(exc), message='Пересчёт не выполнен; сохранён предыдущий результат')
        finally:
            state['running'] = False
            lock.release()

    def schedule():
        interval = int(config.get('auto_update_minutes', 0)) * 60
        if interval <= 0 or offline:
            return
        while True:
            time.sleep(interval)
            update()

    class Handler(BaseHTTPRequestHandler):
        def send(self, content, status=200, mime='application/json; charset=utf-8', extra=None):
            raw = content if isinstance(content, bytes) else content.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers(); self.wfile.write(raw)

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path
            if path in ['/', '/index.html']:
                self.send((root/'web/index.html').read_bytes(), mime='text/html; charset=utf-8')
            elif path.startswith('/assets/'):
                assets = (root/'web/assets').resolve()
                file = (assets/urllib.parse.unquote(path[len('/assets/'):])).resolve()
                types = {'.css':'text/css; charset=utf-8', '.js':'text/javascript; charset=utf-8',
                         '.woff':'font/woff', '.svg':'image/svg+xml'}
                if file.is_relative_to(assets) and file.is_file() and file.suffix in types:
                    self.send(file.read_bytes(), mime=types[file.suffix])
                else:
                    self.send('{"error":"Файл не найден"}',404)
            elif path == '/api/status':
                p = root/'results/current.json'
                self.send(json.dumps({**state, 'offline': offline,
                                      'version': p.stat().st_mtime if p.exists() else None}, ensure_ascii=False))
            elif path == '/api/data':
                file = root/'results/current.json'
                if file.exists():
                    self.send(file.read_bytes())
                else:
                    self.send(json.dumps({'error': 'Данные ещё не подготовлены. Нажми «Обновить данные».'}, ensure_ascii=False),503)
            elif path == '/api/logs':
                p = root/'data/loads.jsonl'
                rows = p.read_text().splitlines()[-30:] if p.exists() else []
                self.send('['+','.join(rows)+']')
            elif path.startswith('/download/'):
                name = path.rsplit('/',1)[-1]
                allowed = {'hourly.csv', 'forecast.csv', 'model_metrics.csv', 'backtest_predictions.csv', 'anomalies.csv'}
                p = root/'results'/name
                if name in allowed and p.exists():
                    self.send(p.read_bytes(), mime='text/csv; charset=utf-8', extra={'Content-Disposition': f'attachment; filename="{name}"'})
                else:
                    self.send('{"error":"Файл не найден"}',404)
            else:
                self.send('{"error":"Страница не найдена"}',404)

        def do_POST(self):
            # Разрешены только запросы с локальной страницы; тело ограничено.
            origin = self.headers.get('Origin')
            allowed_origin = f'http://127.0.0.1:{self.server.server_port}'
            if origin is not None and origin != allowed_origin:
                self.send('{"error":"Недопустимый источник запроса"}',403); return
            if self.path == '/api/update':
                threading.Thread(target=update, daemon=True).start()
                self.send('{"status":"started"}',202)
            elif self.path == '/api/scenario':
                try:
                    length = int(self.headers.get('Content-Length',0))
                    if length > 2048: raise ValueError('Слишком большой запрос')
                    body = json.loads(self.rfile.read(length))
                    delta = float(body['delta'])
                    if not np.isfinite(delta) or not -10 <= delta <= 10:
                        raise ValueError('Изменение температуры должно быть от −10 до +10 °C')
                    with (root/'data/scenario_model.pkl').open('rb') as f: saved = pickle.load(f)
                    x = saved['features'].copy()
                    x['temperature_proxy'] += delta
                    in_range = bool(x['temperature_proxy'].between(*saved['range']).all())
                    x = temperature_features(x)
                    p = np.maximum(0,saved['model'].predict(x))
                    rows = [{'time': str(t), 'predicted':float(y), 'lower':float(max(0,y-saved['width'])),
                             'upper':float(y+saved['width'])} for t,y in zip(x.index,p)]
                    self.send(json.dumps({'rows':rows,'in_range':in_range,'range':saved['range']},ensure_ascii=False))
                except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
                    self.send(json.dumps({'error':str(exc)},ensure_ascii=False),400)
            else:
                self.send('{"error":"Неизвестная операция"}',404)

        def log_message(self, fmt, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', port or config['port']), Handler)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Интерфейс: {url}',flush=True)
    if not (root/'results/current.json').exists():
        threading.Thread(target=update,daemon=True).start()
    threading.Thread(target=schedule,daemon=True).start()
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

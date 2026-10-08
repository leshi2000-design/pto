"""Run the shop LAN server on the computer holding the authoritative database."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import ssl
import threading
import logging
from contextlib import closing
from shop.core import Store
from shop.network import dispatch
from shop import backup, documents


def make_server(root, token, host='127.0.0.1', port=8765):
    root = Path(root).resolve()
    with closing(Store(root)) as store:
        documents.ensure_templates(store)
    mutex = threading.RLock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Never include headers or credentials in logs.
        def do_POST(self):
            if self.path != '/api':
                self.reply(404, {'error': 'Неизвестный адрес'})
                return
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.reply(401, {'error': 'Неверный ключ подключения'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16 * 1024**2:
                    self.reply(413, {'error': 'Слишком большой запрос (максимум 16 МБ)'})
                    return
                payload = json.loads(self.rfile.read(size))
                with mutex, closing(Store(root)) as store:
                    result = dispatch(store, payload['method'], payload.get('args', []), payload.get('kwargs', {}))
                self.reply(200, {'result': result})
            except (ValueError, KeyError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except Exception:
                logging.exception('Server operation failed')
                self.reply(500, {'error': 'Ошибка сервера. Подробности в server-error.log.'})
        def reply(self, status, value):
            content = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.shop_root = root
    server.shop_mutex = mutex
    return server


def main():
    parser = argparse.ArgumentParser(description='Магазин — сервер локальной сети')
    parser.add_argument('--data-dir', default=str(Path.home() / '.magazin'))
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--certificate')
    parser.add_argument('--private-key')
    args = parser.parse_args()
    root = Path(args.data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=root / 'server-error.log', level=logging.ERROR)
    token_path = root / 'server-key.txt'
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), encoding='ascii')
        token_path.chmod(0o600)
    token = token_path.read_text(encoding='ascii').strip()
    server = make_server(root, token, args.host, args.port)
    if bool(args.certificate) != bool(args.private_key):
        parser.error('Укажите и сертификат, и закрытый ключ')
    if args.certificate:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.certificate, args.private_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    stop = threading.Event()
    def periodic_backup():
        while not stop.is_set():
            try:
                with server.shop_mutex, closing(Store(root)) as store:
                    backup.create(store)
            except Exception:
                logging.exception('Scheduled backup failed')
            stop.wait(3600)
    task = threading.Thread(target=periodic_backup, daemon=True)
    task.start()
    def periodic_prices():
        from shop.sources import crawl, apply_web_prices
        while not stop.is_set():
            try:
                with server.shop_mutex, closing(Store(root)) as store:
                    rows = store.rows("SELECT value FROM settings WHERE key='web_sources'")
                    configs = json.loads(rows[0]['value']) if rows else []
                for config in configs:
                    products, errors, limited = crawl(config)
                    with server.shop_mutex, closing(Store(root)) as store:
                        apply_web_prices(store, config, products)
                    if errors or limited:
                        logging.error('Price update incomplete for %s: %s; limited=%s', config['supplier'], errors, limited)
            except Exception:
                logging.exception('Scheduled price update failed')
            stop.wait(3600)
    threading.Thread(target=periodic_prices, daemon=True).start()
    print(f'Сервер Магазина: {args.host}:{args.port}. Ключ подключения: файл {token_path}', flush=True)
    print('База хранится на этом компьютере. Для остановки нажмите Ctrl+C.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        with server.shop_mutex, closing(Store(root)) as store:
            backup.create(store)


if __name__ == '__main__':
    main()

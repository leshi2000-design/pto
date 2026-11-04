"""Сертификаты, брандмауэр и диагностика веб-доступа.

Предупреждение «подключение не защищено» вызывает самоподписанный сертификат: браузер не знает, кому доверять. Здесь создаётся СВОЙ центр сертификации ПТО (один раз), и им
подписывается сертификат веб-сервера (с адресами компьютера в сети). Центр сертификации достаточно один раз установить на устройство (компьютер, телефон) — после этого
сайт открывается с замком и без предупреждений. Файл центра публичен (в нём нет секретов); закрытый ключ центра остаётся на компьютере с базой.
Адрес компьютера в сети может измениться (DHCP) — сертификат сервера выпускается заново сам, доверие к центру при этом сохраняется."""
import hashlib
import http.server
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

CA_NAME = 'ПТО — центр сертификации'
RULE_NAME = 'PTO Web'


def _write_private(path, data):
    path = Path(path)
    path.write_bytes(data)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def ensure_ca(folder):
    """Центр сертификации ПТО (создаётся один раз, 10 лет). Возвращает (cert_path, key_path)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = folder / 'pto-ca.pem', folder / 'pto-ca.key'
    if not (cert_path.exists() and key_path.exists()):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME), x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'ПТО')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
                                             key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .sign(key, hashes.SHA256()))
        _write_private(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def ca_der(folder):
    """Сертификат центра в формате DER (.crt/.cer) для установки на Windows, Android, iPhone."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    cert_path, _key = ensure_ca(folder)
    return x509.load_pem_x509_certificate(cert_path.read_bytes()).public_bytes(serialization.Encoding.DER)


def ca_fingerprint(folder):
    return hashlib.sha256(ca_der(folder)).hexdigest().upper()


def ensure_server_cert(folder, ips=(), hostnames=()):
    """Сертификат веб-сервера, подписанный центром ПТО, с адресами компьютера в сети. Выпускается заново при смене адресов или за 30 дней до конца срока.
    Возвращает (cert_path, key_path)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    folder = Path(folder)
    ca_cert_path, ca_key_path = ensure_ca(folder)
    cert_path, key_path, meta_path = folder / 'web-server.pem', folder / 'web-server.key', folder / 'web-server.json'
    names = sorted({str(i) for i in ips if i} | {'127.0.0.1'})
    dns = sorted({h for h in list(hostnames) + [socket.gethostname(), 'localhost'] if h})
    wanted = dict(ips=names, dns=dns, ca=ca_fingerprint(folder))
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        fresh = datetime.fromisoformat(meta['expires']) - datetime.now(timezone.utc) > timedelta(days=30)
        if cert_path.exists() and key_path.exists() and fresh and all(meta.get(k) == v for k, v in wanted.items()):
            return cert_path, key_path
    except (OSError, ValueError, KeyError):
        pass
    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=800)                                 # iOS требует не более 825 дней
    san = [x509.IPAddress(ipaddress.ip_address(i)) for i in names] + [x509.DNSName(d) for d in dns]
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'ПТО веб-доступ')])).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1)).not_valid_after(expires)
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, content_commitment=False, data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_private(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))     # цепочка: сервер + центр
    meta_path.write_text(json.dumps(dict(wanted, expires=expires.isoformat())), encoding='utf-8')
    return cert_path, key_path


# --- СТРАНИЦА УСТАНОВКИ СЕРТИФИКАТА (обычный HTTP, без секретов) -----------------------------------------

INSTALL_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ПТО — установка сертификата</title>
<style>body{{font:16px/1.5 system-ui,Segoe UI,sans-serif;margin:0;background:#f7f7f8;color:#18181b}}main{{max-width:720px;margin:0 auto;padding:18px}}
.card{{background:#fff;border:1px solid #ececef;border-radius:12px;padding:14px 18px;margin-bottom:12px}}a.btn{{display:inline-block;background:#1b6b62;color:#fff;text-decoration:none;padding:12px 18px;border-radius:10px;font-weight:600}}
code{{background:#f1f1f4;padding:1px 6px;border-radius:6px}}h1{{font-size:22px}}h2{{font-size:17px;margin:4px 0 6px}}</style></head><body><main>
<h1>ПТО: чтобы браузер не писал «подключение не защищено»</h1>
<div class="card"><p>Один раз установите на это устройство сертификат центра ПТО — после этого сайт <b>{https}</b> открывается с замком и без предупреждений.
Сертификат публичный (в нём нет паролей и данных); он нужен только чтобы устройство доверяло вашему компьютеру с ПТО.</p>
<p><a class="btn" href="/pto-ca.crt">Скачать сертификат (pto-ca.crt)</a></p>
<p class="muted">Отпечаток SHA-256 (сверьте с настройками ПТО): <code>{fp}</code></p></div>
<div class="card"><h2>Windows (компьютер)</h2><p>Откройте скачанный файл → «Установить сертификат» → «Локальный компьютер» (или «Текущий пользователь») → «Поместить все сертификаты в следующее хранилище» →
<b>«Доверенные корневые центры сертификации»</b> → Готово. Перезапустите браузер.</p></div>
<div class="card"><h2>Android</h2><p>Настройки → Безопасность (или «Защита и конфиденциальность») → Шифрование и учётные данные → <b>Установить сертификат → Сертификат ЦС</b> → выберите скачанный файл
(подтвердите предупреждение). Затем откройте <b>{https}</b> в Chrome.</p></div>
<div class="card"><h2>iPhone / iPad</h2><p>Скачайте файл → «Настройки» → вверху «Профиль загружен» → Установить. Затем: Настройки → Основные → Об этом устройстве →
<b>Доверие сертификатов</b> → включите доверие для «ПТО — локальный центр сертификации». Затем откройте <b>{https}</b> в Safari.</p></div>
<div class="card"><p>Открыть программу: <a href="{https}">{https}</a></p></div></main></body></html>"""


class InstallServer:
    """Маленький HTTP-сервер (порт веб-доступа + 1): только страница установки сертификата и сам сертификат. Данных ПТО здесь нет."""
    def __init__(self, folder, https_url, host='0.0.0.0', port=0):
        self.folder, self.https_url, self.host, self.port = Path(folder), https_url, host, int(port)
        self.httpd = None
        self.thread = None

    def start(self):
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            server_version = 'PTO'
            sys_version = ''

            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split('?')[0]
                if path in ('/pto-ca.crt', '/pto-ca.cer'):
                    data, ctype = ca_der(owner.folder), 'application/x-x509-ca-cert'
                elif path == '/pto-ca.pem':
                    data, ctype = ensure_ca(owner.folder)[0].read_bytes(), 'application/x-pem-file'
                elif path in ('/', '/index.html'):
                    host = re.sub(r'[^0-9A-Za-z.\-]', '', (self.headers.get('Host') or '').rsplit(':', 1)[0]) or 'localhost'
                    data = INSTALL_HTML.format(https=owner.https_url.replace('{host}', host), fp=':'.join(ca_fingerprint(owner.folder)[i:i + 2] for i in range(0, 64, 2))).encode('utf-8')
                    ctype = 'text/html; charset=utf-8'
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                if path.startswith('/pto-ca.'):
                    self.send_header('Content-Disposition', f'attachment; filename="{path[1:]}"')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(data)
        self.httpd = http.server.ThreadingHTTPServer((self.host, self.port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.3}, daemon=True, name='web-install')
        self.thread.start()
        return self.port

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


# --- БРАНДМАУЭР И ДИАГНОСТИКА -----------------------------------------------------------------------------

def _run(args, timeout=8):
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        out = r.stdout
        for enc in ('utf-8', 'cp866', 'cp1251'):
            try:
                return r.returncode, out.decode(enc)
            except UnicodeDecodeError:
                continue
        return r.returncode, out.decode('utf-8', 'replace')
    except (OSError, subprocess.SubprocessError):
        return -1, ''


def firewall_rule_exists():
    """Есть ли правило брандмауэра Windows «PTO Web»; None — не Windows или проверить не удалось."""
    if sys.platform != 'win32':
        return None
    code, out = _run(['netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={RULE_NAME}'])
    if code == -1:
        return None
    return code == 0 and RULE_NAME.lower() in out.lower()


def firewall_command(ports):
    ports = ','.join(str(p) for p in ports)
    return (f'netsh advfirewall firewall delete rule name="{RULE_NAME}" & '
            f'netsh advfirewall firewall add rule name="{RULE_NAME}" dir=in action=allow protocol=TCP localport={ports} profile=any remoteip=localsubnet')


def open_firewall(ports):
    """Создаёт правило брандмауэра (вход по TCP с адресов своей подсети, для всех типов сети). Windows спросит подтверждение администратора (UAC)."""
    if sys.platform != 'win32':
        return False
    cmd = firewall_command(ports).replace('"', '\\"')
    subprocess.Popen(['powershell', '-NoProfile', '-Command', f'Start-Process cmd -ArgumentList \'/c {cmd}\' -Verb RunAs -WindowStyle Hidden'],
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return True


def network_profiles():
    """Типы сетевых подключений Windows: [(имя, категория)] — «Public» (общедоступная) блокирует входящие подключения строже всего."""
    if sys.platform != 'win32':
        return []
    code, out = _run(['powershell', '-NoProfile', '-Command', 'Get-NetConnectionProfile | ForEach-Object { $_.Name + \"|\" + $_.NetworkCategory }'], timeout=10)
    return [tuple(line.strip().split('|', 1)) for line in out.splitlines() if '|' in line] if code == 0 else []


def lan_addresses():
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith('127.') and not ip.startswith('169.254.') and ip not in found:
                found.append(ip)
    except OSError:
        pass
    try:                                                           # адрес «по умолчанию» (через который идёт выход в сеть) — самый надёжный
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        if ip not in found and not ip.startswith('127.'):
            found.insert(0, ip)
    except OSError:
        pass
    return found


def can_connect(ip, port, timeout=2):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def diagnose(gateway, install_port=None):
    """Причины, по которым телефон может не открывать сайт: [(уровень 'ok'|'warn'|'err', текст)]."""
    out = []
    if not gateway:
        return [('err', 'Веб-доступ выключен или не запустился: включите его и нажмите «Применить».')]
    ips = lan_addresses()
    out.append(('ok', f'Сервер запущен, порт {gateway.port}' + (f', страница сертификата — порт {install_port}' if install_port else '') + '.'))
    if not ips:
        out.append(('err', 'У компьютера нет адреса в локальной сети: подключитесь к Wi‑Fi или кабелю.'))
    for ip in ips:
        ok = can_connect(ip, gateway.port)
        out.append(('ok' if ok else 'err', f'Адрес {ip}: ' + ('порт отвечает с этого компьютера.' if ok else 'порт не отвечает даже с самого компьютера — порт занят другой программой или сервер не запущен.')))
    rule = firewall_rule_exists()
    if rule is False:
        out.append(('err', 'В брандмауэре Windows НЕТ правила для ПТО — это самая частая причина, почему телефон не заходит. Нажмите «Разрешить в брандмауэре» (потребуется подтверждение администратора).'))
    elif rule:
        out.append(('ok', 'Правило брандмауэра «PTO Web» есть.'))
    for name, category in network_profiles():
        if category.lower() == 'public':
            out.append(('warn', f'Сеть «{name}» в Windows помечена как «Общедоступная»: если правило создано с типом «Любой» (кнопка «Разрешить в брандмауэре» делает именно так) — это не мешает; иначе смените на «Частная».'))
    if len(ips) > 1:
        out.append(('warn', 'У компьютера несколько сетевых адресов (' + ', '.join(ips) + '): телефон должен быть в той же сети, что и тот адрес, который вы открываете.'))
    out.append(('warn', 'Телефон и компьютер должны быть в ОДНОЙ сети: первые три числа адресов совпадают (например, 192.168.0.x). «Гостевая» сеть Wi‑Fi и режим «изоляция клиентов» (AP isolation) в роутере запрещают устройствам видеть друг друга.'))
    out.append(('warn', 'Мобильный интернет на телефоне должен быть выключен, а VPN/«частный DNS»-приложения — отключены: иначе телефон отправит запрос не в вашу сеть.'))
    return out

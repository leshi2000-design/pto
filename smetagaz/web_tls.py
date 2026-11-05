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
<div class="card"><h2>Windows: одним файлом</h2><p>Скачайте и запустите <a href="/pto-web-setup.bat">pto-web-setup.bat</a>: он установит сертификат (Windows спросит «Да/Нет» — нажмите «Да») и создаст на рабочем столе ярлык «ПТО (веб)» на портал. Браузер может предупредить о скачивании .bat — это обычный текстовый сценарий, его содержимое можно открыть блокнотом.
Только ярлык без сертификата: <a href="/pto.url">pto.url</a>.</p></div>
<div class="card"><h2>Windows (компьютер), вручную</h2><p>Откройте скачанный файл → «Установить сертификат» → «Локальный компьютер» (или «Текущий пользователь») → «Поместить все сертификаты в следующее хранилище» →
<b>«Доверенные корневые центры сертификации»</b> → Готово. Перезапустите браузер.</p></div>
<div class="card"><h2>Android</h2><p>Настройки → Безопасность (или «Защита и конфиденциальность») → Шифрование и учётные данные → <b>Установить сертификат → Сертификат ЦС</b> → выберите скачанный файл
(подтвердите предупреждение). Затем откройте <b>{https}</b> в Chrome.</p></div>
<div class="card"><h2>iPhone / iPad</h2><p>Скачайте файл → «Настройки» → вверху «Профиль загружен» → Установить. Затем: Настройки → Основные → Об этом устройстве →
<b>Доверие сертификатов</b> → включите доверие для «ПТО — локальный центр сертификации». Затем откройте <b>{https}</b> в Safari.</p></div>
<div class="card"><p>Открыть программу: <a href="{https}">{https}</a></p></div></main></body></html>"""


SHORTCUT_NAME = 'ПТО (веб).url'


def shortcut_text(url):
    return f'[InternetShortcut]\r\nURL={url}\r\n'


def setup_script(url, base):
    """Файл .bat для Windows: один раз ставит сертификат ПТО (для текущего пользователя, без прав администратора — Windows спросит подтверждение) и создаёт на рабочем столе ярлык на портал.
    Сам сценарий PowerShell передаётся закодированным, поэтому кириллица и кавычки не ломаются."""
    ps = ("$ErrorActionPreference='Stop'\n"
          "Add-Type -AssemblyName System.Windows.Forms\n"
          f"$url='{url}'\n$base='{base}'\n"
          "$msg=''\n"
          "try { $f=Join-Path $env:TEMP 'pto-ca.crt'; Invoke-WebRequest -UseBasicParsing -Uri ($base+'/pto-ca.crt') -OutFile $f; "
          "Import-Certificate -FilePath $f -CertStoreLocation Cert:\\CurrentUser\\Root | Out-Null; Remove-Item $f -ErrorAction SilentlyContinue; $msg+='Сертификат ПТО установлен.'+[Environment]::NewLine } "
          "catch { $msg+='Сертификат установить не удалось ('+$_.Exception.Message+'). Откройте '+$base+' и установите его вручную.'+[Environment]::NewLine }\n"
          "try { $d=[Environment]::GetFolderPath('Desktop'); $p=Join-Path $d '" + SHORTCUT_NAME + "'; "
          "[IO.File]::WriteAllText($p, \"[InternetShortcut]`r`nURL=$url`r`n\", [Text.Encoding]::ASCII); $msg+='Ярлык создан на рабочем столе: " + SHORTCUT_NAME + "' } "
          "catch { $msg+='Ярлык создать не удалось: '+$_.Exception.Message }\n"
          "[System.Windows.Forms.MessageBox]::Show($msg,'ПТО — веб-доступ') | Out-Null\n")
    import base64
    encoded = base64.b64encode(ps.encode('utf-16-le')).decode('ascii')
    return f'@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}\r\n'


def desktop_folder():
    """Рабочий стол текущего пользователя (с учётом перенаправления в OneDrive)."""
    if sys.platform == 'win32':
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(0, 0x0000, 0, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / 'Desktop'


def create_desktop_shortcut(url, folder=None):
    """Создаёт на рабочем столе этого компьютера ярлык на портал ПТО. Возвращает путь к ярлыку."""
    folder = Path(folder) if folder else desktop_folder()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SHORTCUT_NAME
    path.write_bytes(shortcut_text(url).encode('ascii'))
    return path


def install_page(folder, https_url, path, host_header=''):
    """(код, данные, тип, заголовки) для страницы установки сертификата и самого сертификата; другие адреса — 404."""
    path = path.split('?')[0]
    if path in ('/pto-ca.crt', '/pto-ca.cer'):
        return 200, ca_der(folder), 'application/x-x509-ca-cert', [('Content-Disposition', f'attachment; filename="{path[1:]}"')]
    if path == '/pto-ca.pem':
        return 200, ensure_ca(folder)[0].read_bytes(), 'application/x-pem-file', [('Content-Disposition', 'attachment; filename="pto-ca.pem"')]
    host = re.sub(r'[^0-9A-Za-z.\-]', '', host_header.rsplit(':', 1)[0]) or 'localhost'
    if path == '/pto.url':
        return 200, shortcut_text(https_url.replace('{host}', host)).encode('ascii', 'replace'), 'application/octet-stream', [('Content-Disposition', 'attachment; filename="pto.url"')]
    if path == '/pto-web-setup.bat':
        base = 'http://' + re.sub(r'[^0-9A-Za-z.\-:]', '', host_header or host)
        return 200, setup_script(https_url.replace('{host}', host), base).encode('ascii'), 'application/octet-stream', [('Content-Disposition', 'attachment; filename="pto-web-setup.bat"')]
    if path in ('/', '/index.html'):
        fp = ca_fingerprint(folder)
        return 200, INSTALL_HTML.format(https=https_url.replace('{host}', host), fp=':'.join(fp[i:i + 2] for i in range(0, 64, 2))).encode('utf-8'), 'text/html; charset=utf-8', []
    return 404, b'', 'text/plain', []


def install_handler(context):
    """Класс обработчика HTTP для страницы установки сертификата; context() -> (папка, адрес https)."""
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = 'PTO'
        sys_version = ''

        def log_message(self, *a):
            pass

        def do_GET(self):
            folder, https_url = context()
            code, data, ctype, headers = install_page(folder, https_url, self.path, self.headers.get('Host') or '')
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)
    return Handler


class InstallServer:
    """Маленький HTTP-сервер (порт веб-доступа + 1): только страница установки сертификата и сам сертификат. Данных ПТО здесь нет."""
    def __init__(self, folder, https_url, host='0.0.0.0', port=0):
        self.folder, self.https_url, self.host, self.port = Path(folder), https_url, host, int(port)
        self.httpd = None
        self.thread = None

    def start(self):
        self.httpd = http.server.ThreadingHTTPServer((self.host, self.port), install_handler(lambda: (self.folder, self.https_url)))
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


PRIVATE_RANGES = 'LocalSubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16'      # своя сеть, в том числе соседняя подсеть роутера (кабель и Wi‑Fi бывают в разных); интернет — нет


def firewall_command(ports):
    ports = ','.join(str(p) for p in ports)
    return (f'netsh advfirewall firewall delete rule name="{RULE_NAME}" & '
            f'netsh advfirewall firewall add rule name="{RULE_NAME}" dir=in action=allow protocol=TCP localport={ports} profile=any remoteip={PRIVATE_RANGES}')


def firewall_script(ports, exe=None):
    """Сценарий PowerShell (от администратора): снимает запрещающие правила Windows для программы (их создаёт отказ в окне «Разрешить доступ» при первом запуске —
    запрет сильнее любого разрешения), создаёт разрешающие правила по портам и для самой программы."""
    exe = exe or sys.executable
    ports = ','.join(str(p) for p in ports)
    return (f"$ErrorActionPreference='SilentlyContinue'\n"
            f"$exe='{exe.replace(chr(39), chr(39) * 2)}'\n"
            "Get-NetFirewallApplicationFilter | Where-Object { $_.Program -eq $exe } | Get-NetFirewallRule | Where-Object { $_.Action -eq 'Block' -and $_.Direction -eq 'Inbound' } | Remove-NetFirewallRule\n"
            f'netsh advfirewall firewall delete rule name="{RULE_NAME}" | Out-Null\n'
            f'netsh advfirewall firewall delete rule name="{RULE_NAME} (программа)" | Out-Null\n'
            f'netsh advfirewall firewall add rule name="{RULE_NAME}" dir=in action=allow protocol=TCP localport={ports} profile=any remoteip={PRIVATE_RANGES} | Out-Null\n'
            f'netsh advfirewall firewall add rule name="{RULE_NAME} (программа)" dir=in action=allow program="$exe" profile=any remoteip={PRIVATE_RANGES} | Out-Null\n')


def open_firewall(ports):
    """Создаёт правила брандмауэра (вход по TCP из своей сети, для всех типов сети). Windows спросит подтверждение администратора (UAC)."""
    if sys.platform != 'win32':
        return False
    import base64
    encoded = base64.b64encode(firewall_script(ports).encode('utf-16-le')).decode('ascii')
    subprocess.Popen(['powershell', '-NoProfile', '-Command', f"Start-Process powershell -ArgumentList '-NoProfile','-EncodedCommand','{encoded}' -Verb RunAs -WindowStyle Hidden"],
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return True


def blocking_rules():
    """Запрещающие входящие правила Windows для этой программы (None — не Windows / проверить не удалось)."""
    if sys.platform != 'win32':
        return None
    exe = sys.executable.replace("'", "''")
    code, out = _run(['powershell', '-NoProfile', '-Command',
                      f"Get-NetFirewallApplicationFilter | Where-Object {{ $_.Program -eq '{exe}' }} | Get-NetFirewallRule | Where-Object {{ $_.Action -eq 'Block' -and $_.Direction -eq 'Inbound' -and $_.Enabled -eq 'True' }} | ForEach-Object {{ $_.DisplayName }}"], timeout=15)
    return [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else None


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
    blocked = blocking_rules()
    if blocked:
        out.append(('err', 'В брандмауэре Windows есть ЗАПРЕЩАЮЩЕЕ правило для программы (' + ', '.join(blocked[:3]) + ') — оно сильнее любого разрешения. Его создаёт отказ в окне «Разрешить доступ» при первом запуске. '
                    'Кнопка «Разрешить в брандмауэре» снимает такие правила.'))
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
    out.append(('warn', 'Ошибка телефона «ERR_ADDRESS_UNREACHABLE» (нет маршрута до узла) почти всегда значит, что запрос НЕ дошёл до компьютера: 1) Android «ушёл» с Wi‑Fi на мобильные данные, '
                        'потому что у Wi‑Fi нет интернета (выключите мобильные данные и «Умное переключение сети / Wi‑Fi+» в настройках Wi‑Fi); 2) телефон в другой сети или подсети '
                        '(у телефона и компьютера должны совпадать первые три числа адреса); 3) роутер запрещает устройствам видеть друг друга («изоляция клиентов», «гостевая сеть»). '
                        'Брандмауэр так не отвечает — при блокировке страница долго висит и пишет «слишком долго отвечает» (ERR_CONNECTION_TIMED_OUT).'))
    out.append(('warn', 'Мобильный интернет на телефоне должен быть выключен, а VPN/«частный DNS»-приложения — отключены: иначе телефон отправит запрос не в вашу сеть.'))
    return out

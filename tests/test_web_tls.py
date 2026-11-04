"""Сертификат веб-доступа: собственный центр ПТО подписывает сертификат сервера; устройство, где установлен центр, видит сайт без предупреждения; страница установки; диагностика."""
import http.client
import ssl

import pytest

from smetagaz import web_gateway as wg, web_tls
from test_web_gateway import db  # noqa: F401


def test_ca_and_server_certificate(tmp_path):
    cert, key = web_tls.ensure_server_cert(tmp_path, ['127.0.0.1', '192.168.1.50'], ['pc-office'])
    assert cert.exists() and key.exists() and (tmp_path / 'pto-ca.pem').exists()
    der = web_tls.ca_der(tmp_path)
    assert len(web_tls.ca_fingerprint(tmp_path)) == 64 and der[:1] == b'\x30'
    again = web_tls.ensure_server_cert(tmp_path, ['127.0.0.1', '192.168.1.50'], ['pc-office'])
    assert again == (cert, key) and cert.stat().st_mtime_ns == again[0].stat().st_mtime_ns            # без изменений адресов сертификат не перевыпускается
    stamp = cert.read_bytes()
    web_tls.ensure_server_cert(tmp_path, ['127.0.0.1', '192.168.1.77'], ['pc-office'])
    assert cert.read_bytes() != stamp                                                                  # адрес сменился (другая сеть) — выпущен новый
    from cryptography import x509
    leaf = x509.load_pem_x509_certificates(cert.read_bytes())[0]
    names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert '192.168.1.77' in [str(i) for i in names.get_values_for_type(x509.IPAddress)] and 'pc-office' in names.get_values_for_type(x509.DNSName)


def test_device_trusting_pto_ca_sees_no_warning(db, tmp_path):
    wg.add_user(db, 'user1', 'password123', 'viewer')
    cert, key = web_tls.ensure_server_cert(tmp_path, ['127.0.0.1'], ['localhost'])
    g = wg.WebGateway(db, '127.0.0.1', 0, cert, key)
    g.start()
    try:
        trusting = ssl.create_default_context(cafile=str(tmp_path / 'pto-ca.pem'))          # устройство, на котором установлен центр ПТО
        conn = http.client.HTTPSConnection('127.0.0.1', g.port, context=trusting, timeout=10)
        conn.request('GET', '/health')
        assert conn.getresponse().read() == b'ok'
        strict = http.client.HTTPSConnection('127.0.0.1', g.port, context=ssl.create_default_context(), timeout=10)      # устройство без центра ПТО — предупреждение
        with pytest.raises(ssl.SSLError):
            strict.request('GET', '/health')
    finally:
        g.stop()


def test_install_page_and_certificate_download(tmp_path):
    web_tls.ensure_ca(tmp_path)
    srv = web_tls.InstallServer(tmp_path, 'https://{host}:8765', '127.0.0.1', 0)
    srv.start()
    try:
        conn = http.client.HTTPConnection('127.0.0.1', srv.port, timeout=10)
        conn.request('GET', '/', headers={'Host': '192.168.0.5:8766'})
        r = conn.getresponse()
        page = r.read().decode('utf-8')
        assert r.status == 200 and 'https://192.168.0.5:8765' in page and web_tls.ca_fingerprint(tmp_path)[:2] in page.upper()
        conn.request('GET', '/pto-ca.crt')
        r = conn.getresponse()
        data = r.read()
        assert r.status == 200 and data == web_tls.ca_der(tmp_path) and 'attachment' in r.getheader('Content-Disposition')
        conn.request('GET', '/etc/passwd')
        assert conn.getresponse().status == 404
        conn.request('GET', '/', headers={'Host': '"><script>alert(1)</script>'})
        assert '<script>alert(1)' not in conn.getresponse().read().decode('utf-8')
    finally:
        srv.stop()


def test_start_from_settings_https_with_installer_and_diagnostics(db, tmp_path):
    if getattr(db, 'is_remote', False):
        pytest.skip('веб-шлюз запускается только на компьютере с локальной базой')
    db.set_setting('web_enabled', '1')
    db.set_setting('web_https', '1')
    db.set_setting('web_port', '0')
    gw, err = wg.apply_settings(db, tmp_path)
    try:
        assert gw is not None and err == '' and gw.https and gw.installer is not None and wg.install_urls() and wg.install_urls()[0].startswith('http://')
        report = web_tls.diagnose(gw, gw.installer.port)
        assert report[0][0] == 'ok' and any('ОДНОЙ сети' in text for _lvl, text in report)
        assert 'netsh advfirewall' in web_tls.firewall_command([8765, 8766]) and 'Remove-NetFirewallRule' in web_tls.firewall_script([8765], 'C:\\PTO.exe') and '8765,8766' in web_tls.firewall_command([8765, 8766])
    finally:
        db.set_setting('web_enabled', '0')
        wg.apply_settings(db, tmp_path)
    assert wg.RUNNING is None and wg.install_urls() == []
    assert web_tls.diagnose(None)[0][0] == 'err'


def test_stalled_or_plain_connections_do_not_block_https_server(db, tmp_path):
    import socket
    cert, key = web_tls.ensure_server_cert(tmp_path, ['127.0.0.1'], ['localhost'])
    g = wg.WebGateway(db, '127.0.0.1', 0, cert, key)
    g.start()
    stalled = []
    try:
        for _ in range(3):                                                   # телефон открыл соединение и не завершил рукопожатие TLS
            s = socket.create_connection(('127.0.0.1', g.port))
            s.send(b'\x16\x03\x01')
            stalled.append(s)
        trusting = ssl.create_default_context(cafile=str(tmp_path / 'pto-ca.pem'))
        conn = http.client.HTTPSConnection('127.0.0.1', g.port, context=trusting, timeout=5)
        conn.request('GET', '/health')
        assert conn.getresponse().read() == b'ok'                            # остальные клиенты обслуживаются
        plain = http.client.HTTPConnection('127.0.0.1', g.port, timeout=5)   # http:// на порту https — страница установки сертификата, а не ошибка протокола
        plain.request('GET', '/', headers={'Host': '192.168.0.5:8765'})
        r = plain.getresponse()
        page = r.read().decode('utf-8')
        assert r.status == 200 and 'https://192.168.0.5:' in page and 'сертификат' in page
        plain.request('GET', '/pto-ca.crt')
        assert plain.getresponse().read() == web_tls.ca_der(tmp_path)
    finally:
        for s in stalled:
            s.close()
        g.stop()


def test_setup_script_shortcut_and_download_routes(db, tmp_path):
    import base64
    import re
    from test_web_gateway import Client
    script = web_tls.setup_script('https://192.168.0.5:8765/', 'http://192.168.0.5:8766')
    assert script.startswith('@echo off') and script.isascii() and len(script) < 7000                       # лимит командной строки cmd — 8191 символ
    ps = base64.b64decode(re.search(r'-EncodedCommand (\S+)', script).group(1)).decode('utf-16-le')
    assert 'https://192.168.0.5:8765/' in ps and 'pto-ca.crt' in ps and 'CurrentUser' in ps and 'ПТО (веб).url' in ps
    path = web_tls.create_desktop_shortcut('https://192.168.0.5:8765/', tmp_path / 'Desktop')
    assert path.read_bytes() == b'[InternetShortcut]\r\nURL=https://192.168.0.5:8765/\r\n' and path.name == 'ПТО (веб).url'
    # скачивание со страницы установки и из портала
    web_tls.ensure_ca(tmp_path / 'ca')
    srv = web_tls.InstallServer(tmp_path / 'ca', 'https://{host}:8765/', '127.0.0.1', 0)
    srv.start()
    try:
        conn = http.client.HTTPConnection('127.0.0.1', srv.port, timeout=5)
        conn.request('GET', '/pto-web-setup.bat', headers={'Host': '10.0.0.7:8766'})
        r = conn.getresponse()
        bat = r.read().decode('ascii')
        assert r.status == 200 and 'attachment' in r.getheader('Content-Disposition') and 'http://10.0.0.7:8766' in base64.b64decode(re.search(r'-EncodedCommand (\S+)', bat).group(1)).decode('utf-16-le')
        conn.request('GET', '/pto.url', headers={'Host': '10.0.0.7:8766'})
        assert 'URL=https://10.0.0.7:8765/' in conn.getresponse().read().decode()
    finally:
        srv.stop()
    wg.add_user(db, 'user1', 'password123', 'viewer')
    cert, key = web_tls.ensure_server_cert(tmp_path / 'web', ['127.0.0.1'], ['localhost'])
    g = wg.WebGateway(db, '127.0.0.1', 0, cert, key)
    g.start()
    try:
        ctx = ssl.create_default_context(cafile=str(tmp_path / 'web' / 'pto-ca.pem'))

        class TlsClient(Client):
            def request(self, method, path, form=None):
                import urllib.parse as up
                conn = http.client.HTTPSConnection('127.0.0.1', self.gw.port, context=ctx, timeout=10)
                headers = {'Cookie': self.cookie} if self.cookie else {}
                body = up.urlencode(form) if form is not None else None
                if body is not None:
                    headers['Content-Type'] = 'application/x-www-form-urlencoded'
                conn.request(method, path, body, headers)
                resp = conn.getresponse()
                text = resp.read().decode('utf-8')
                sc = resp.getheader('Set-Cookie')
                if sc and sc.startswith('pto_session='):
                    self.cookie = sc.split(';')[0]
                return resp.status, text, dict(resp.getheaders())
        c = TlsClient(g)
        assert c.request('GET', '/download/pto.url')[0] == 303                                                  # без входа недоступно
        c.login('user1', 'password123')
        status, page, _h = c.request('GET', '/setup')
        assert status == 200 and 'pto-web-setup.bat' in page and 'Ярлык на рабочий стол' in page
        status, text, headers = c.request('GET', '/download/pto-web-setup.bat')
        assert status == 200 and text.startswith('@echo off') and 'attachment' in headers['Content-Disposition']
        assert 'URL=https://localhost:' in c.request('GET', '/download/pto.url')[1] or 'URL=https://127.0.0.1:' in c.request('GET', '/download/pto.url')[1]
    finally:
        g.stop()

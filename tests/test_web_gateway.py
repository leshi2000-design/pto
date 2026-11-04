import http.client
import re
import ssl
import urllib.parse

import pytest

from smetagaz.database import DatabaseManager
from smetagaz import web_gateway as wg, web_cards as wc


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def make_contract(db, name='Иванов Иван', phone='375291112233', legal=False):
    cid = db.execute("INSERT INTO crm.clients(name,phone,address,passport,passport_issuer,passport_date) VALUES(?,?,?,?,?,?)",
                     (name, phone, 'Минск, ул. Садовая 1', 'MC1234567', 'Октябрьским РУВД', '2020-03-12')).lastrowid
    contract = db.execute("INSERT INTO contracts(contract_number,contract_date,object_name,object_address,client_id,client_name,client_phone,seq_num,year_num) VALUES(?,?,?,?,?,?,?,?,?)",
                          ('01-02/26', '2026-10-05', 'Жилой дом', 'Минск, Лесная 5', cid, name, phone, 1, 26)).lastrowid
    db.execute("INSERT INTO gsvm_equipment(contract_id,kind,model,serial,note,file_path) VALUES(?,?,?,?,?,?)", (contract, 'Котел', 'Bosch 6000', 'SN-1', '', '/data/passport.pdf'))
    return contract


class Client:
    """Мини-браузер: cookie и запросы к тестовому шлюзу."""
    def __init__(self, gateway, tls=False):
        self.gw, self.tls, self.cookie = gateway, tls, ''

    def request(self, method, path, form=None):
        conn = (http.client.HTTPSConnection('127.0.0.1', self.gw.port, context=ssl._create_unverified_context(), timeout=10) if self.tls
                else http.client.HTTPConnection('127.0.0.1', self.gw.port, timeout=10))
        headers = {'Cookie': self.cookie} if self.cookie else {}
        body = urllib.parse.urlencode(form) if form is not None else None
        if body is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        conn.request(method, path, body, headers)
        r = conn.getresponse()
        text = r.read().decode('utf-8')
        sc = r.getheader('Set-Cookie')
        if sc and sc.startswith('pto_session='):
            self.cookie = sc.split(';')[0]
        out = (r.status, text, dict(r.getheaders()))
        conn.close()
        return out

    def raw_post(self, path, body):
        conn = http.client.HTTPConnection('127.0.0.1', self.gw.port, timeout=10)
        conn.request('POST', path, body, {'Cookie': self.cookie, 'Content-Type': 'application/x-www-form-urlencoded'})
        r = conn.getresponse()
        out = (r.status, r.read().decode('utf-8'), dict(r.getheaders()))
        conn.close()
        return out

    def login(self, user, password):
        return self.request('POST', '/login', dict(login=user, password=password))

    def csrf(self, path):
        return re.search(r'name="csrf" value="([^"]+)"', self.request('GET', path)[1]).group(1)


@pytest.fixture
def gateway(db):
    g = wg.WebGateway(db, '127.0.0.1', 0)
    g.start()
    yield g
    g.stop()


def test_users_and_passwords(db):
    uid = wg.add_user(db, 'anna', 'password123', 'editor')
    assert wg.verify(db, 'anna', 'password123') == (uid, 'editor') and wg.verify(db, 'ANNA', 'password123')[0] == uid
    assert wg.verify(db, 'anna', 'wrong') is None and wg.verify(db, 'nobody', 'x') is None
    with pytest.raises(ValueError, match='8 символов'):
        wg.add_user(db, 'bob', 'short', 'viewer')
    with pytest.raises(ValueError):
        wg.add_user(db, 'anna', 'password123', 'viewer')
    with pytest.raises(ValueError):
        wg.add_user(db, 'x y', 'password123', 'viewer')
    wg.set_user(db, uid, active=False)
    assert wg.verify(db, 'anna', 'password123') is None
    wg.set_user(db, uid, active=True)
    wg.set_password(db, uid, 'newpassword9')
    assert wg.verify(db, 'anna', 'password123') is None and wg.verify(db, 'anna', 'newpassword9')
    assert db.fetchone('SELECT hash FROM web_users WHERE id=?', (uid,))[0] != 'newpassword9'          # пароль в базе только в виде хэша


def test_card_domain(db):
    cid = make_contract(db)
    card = wc.get_card(db, cid)
    assert card['client']['name'] == 'Иванов Иван' and card['equipment'][0]['model'] == 'Bosch 6000'
    assert wc.phones_from_lines('375291112233 (основной)\n\n375447778899') == '375291112233 (основной); 375447778899'
    assert wc.phones_to_lines('375291112233 (основной); 375447778899') == '375291112233 (основной)\n375447778899'
    eq = card['equipment'][0]
    saved = wc.save_card(db, cid, dict(client_name='Иванов Иван Иванович', phones='375291112233\n375447778899 (жена)', client_address='Минск', passport='MC7654321', passport_issuer='РУВД',
                                       passport_date='2021-01-02', object='Дом', object_address='Лесная 7', notes='звонить после 18', signed='1'),
                         [dict(id=eq['id'], kind='Котел', model='Viessmann', serial='SN-9', note='новый'), dict(id=None, kind='Колонка', model='Neva', serial='K-1')])
    assert saved['client']['phone'] == '375291112233; 375447778899 (жена)' and saved['signed'] and not saved['act_signed']
    assert db.fetchone('SELECT phone FROM crm.clients WHERE id=?', (card['client_id'],))[0] == '375291112233; 375447778899 (жена)'
    assert db.fetchone('SELECT client_phone,passport_series_number FROM contracts WHERE id=?', (cid,)) == ('375291112233; 375447778899 (жена)', 'MC7654321')
    equipment = {e['kind']: e for e in saved['equipment']}
    assert equipment['Котел']['model'] == 'Viessmann' and equipment['Котел']['file_path'] == '/data/passport.pdf' and equipment['Колонка']['serial'] == 'K-1'       # файл паспорта сохранён
    text = wc.copy_text(db, cid)
    assert 'ФИО: Иванов Иван Иванович' in text and 'Котел: модель Viessmann, серийный номер SN-9' in text and 'Дата выдачи: 02.01.2021' in text
    wc.save_card(db, cid, dict(client_name='Иванов Иван Иванович', phones='1', object='Дом'), [dict(id=equipment['Колонка']['id'], delete=True)])
    assert [e['kind'] for e in wc.get_card(db, cid)['equipment']] == ['Котел']
    with pytest.raises(ValueError, match='ФИО'):
        wc.save_card(db, cid, dict(client_name='', phones=''))
    with pytest.raises(ValueError, match='ГГГГ-ММ-ДД'):
        wc.save_card(db, cid, dict(client_name='А', passport_date='12.03.2020'))
    with pytest.raises(ValueError, match='не относится'):
        wc.save_card(db, cid, dict(client_name='А'), [dict(id=99999, kind='Котел')])
    assert wc.search(db, 'viessmann') == [] and [c['id'] for c in wc.search(db, '375447778899')] == []     # поиск по телефону договора ищет в его снимке
    assert [c['id'] for c in wc.search(db, 'дом')] == [cid]


def test_http_flow_security_and_editing(db, gateway):
    cid = make_contract(db, name='<script>alert(1)</script>')
    wg.add_user(db, 'viewer1', 'viewerpass1', 'viewer')
    wg.add_user(db, 'editor1', 'editorpass1', 'editor')
    anon = Client(gateway)
    status, body, headers = anon.request('GET', '/contracts')
    assert status == 303 and headers['Location'] == '/login'
    assert anon.request('GET', '/health')[1] == 'ok'
    assert anon.request('GET', f'/m/contracts/{cid}')[0] == 303                           # без входа карточка недоступна
    assert anon.login('editor1', 'bad')[0] == 401
    # защита от подбора пароля
    for _ in range(5):
        anon.login('editor1', 'bad')
    assert anon.login('editor1', 'editorpass1')[0] == 429
    # наблюдатель: чтение есть, правки нет
    v = Client(gateway)
    v.gw = wg.WebGateway(db, '127.0.0.1', 0)                                            # отдельный шлюз-счётчик попыток не нужен: сбросим блокировку
    v.gw = gateway
    gateway.fails.clear()
    assert v.login('viewer1', 'viewerpass1')[0] == 303
    status, page, headers = v.request('GET', '/m/contracts')
    assert status == 200 and '01-02/26' in page and 'Content-Security-Policy' in headers and headers['X-Frame-Options'] == 'DENY' and headers['Cache-Control'] == 'no-store'
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page and '<script>alert(1)' not in page            # экранирование
    status, page, _h = v.request('GET', f'/m/contracts/{cid}')
    assert status == 200 and 'Только просмотр' in page and 'disabled' in page and 'SN-1' in page and 'ФИО:' in page
    assert v.request('POST', f'/m/contracts/{cid}', {'csrf': v.csrf(f'/m/contracts/{cid}'), 'f_client_name': 'Взлом'})[0] == 403
    # сотрудник
    e = Client(gateway)
    assert e.login('editor1', 'editorpass1')[0] == 303
    assert e.request('POST', f'/m/contracts/{cid}', {'f_client_name': 'Без csrf'})[0] == 403           # CSRF-токен обязателен
    token = e.csrf(f'/m/contracts/{cid}')
    eqid = str(wc.get_card(db, cid)['equipment'][0]['id'])
    form = {'csrf': token, 'f_client_name': 'Петров Пётр', 'f_phones': '375291111111\n375292222222 (доп)', 'f_client_address': 'Брест', 'f_passport': 'AB123', 'f_passport_issuer': 'РУВД',
            'f_passport_date': '2019-05-06', 'f_object': 'Склад', 'f_object_address': 'Брест, Заводская 1', 'f_notes': 'примечание', 'f_signed': '1', 'c_equipment_count': '2',
            'c_equipment_id_0': eqid, 'c_equipment_kind_0': 'Котел', 'c_equipment_model_0': 'Новая модель', 'c_equipment_serial_0': 'SN-2', 'c_equipment_note_0': '',
            'c_equipment_id_1': '', 'c_equipment_kind_1': '', 'c_equipment_model_1': '', 'c_equipment_serial_1': '', 'c_equipment_note_1': ''}
    status, page, _h = e.request('POST', f'/m/contracts/{cid}', form)
    assert status == 200 and 'Сохранено.' in page and '375292222222 (доп)' in page
    assert db.fetchone('SELECT client_name,client_phone FROM contracts WHERE id=?', (cid,)) == ('Петров Пётр', '375291111111; 375292222222 (доп)')
    # ошибка проверки данных
    bad = dict(form, f_client_name='')
    assert 'Введите ФИО клиента' in e.request('POST', f'/m/contracts/{cid}', bad)[1]
    # блокировка: карточка открыта в программе
    db.execute("INSERT INTO edit_locks(key,sid,user,host,since,beat) VALUES(?,?,?,?,?,CAST(strftime('%s','now') AS INTEGER))", (f'gsvm:{cid}', 'x', 'Мария', 'PC-2', ''))
    status, page, _h = e.request('POST', f'/m/contracts/{cid}', dict(form, f_client_name='Под замком'))
    assert 'Мария' in page and db.fetchone('SELECT client_name FROM contracts WHERE id=?', (cid,))[0] == 'Петров Пётр'
    # выход
    assert e.request('POST', '/logout', dict(csrf=token))[0] == 303
    assert e.request('GET', '/m/contracts')[0] == 303
    assert e.request('GET', '/nope')[0] in (303, 404)


def test_https_gateway_sets_secure_cookie(db, tmp_path):
    from smetagaz.server_core import ensure_certificate
    cert, key, _fp = ensure_certificate(str(tmp_path / 'cert'), ['127.0.0.1'])
    wg.add_user(db, 'u1', 'password123', 'viewer')
    g = wg.WebGateway(db, '127.0.0.1', 0, cert, key)
    g.start()
    try:
        conn = http.client.HTTPSConnection('127.0.0.1', g.port, context=ssl._create_unverified_context(), timeout=10)
        conn.request('POST', '/login', urllib.parse.urlencode(dict(login='u1', password='password123')), {'Content-Type': 'application/x-www-form-urlencoded'})
        r = conn.getresponse()
        r.read()
        cookie = r.getheader('Set-Cookie')
        assert r.status == 303 and 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie
    finally:
        g.stop()


def test_apply_settings_and_urls(db, tmp_path):
    if getattr(db, 'is_remote', False):
        pytest.skip('веб-шлюз запускается только на компьютере с локальной базой')
    db.set_setting('web_enabled', '1')
    db.set_setting('web_https', '0')
    db.set_setting('web_port', '0')
    gw, err = wg.apply_settings(db, tmp_path)
    assert gw is not None and err == '' and wg.urls() and wg.urls()[0].startswith('http://')
    db.set_setting('web_enabled', '0')
    assert wg.apply_settings(db, tmp_path)[0] is None and wg.urls() == []


def test_settings_box_and_users_dialog(db, tmp_path, monkeypatch):
    import sys
    from smetagaz import web_settings_ui as ws, settings_view  # noqa: F401
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: 0)
    monkeypatch.setattr(ws, 'DATA_DIR', tmp_path)
    wg.add_user(db, 'anna', 'password123', 'editor')
    box = ws.WebAccessBox()
    assert box.status.text() == 'Выключен.'
    box.enabled.setChecked(True)
    box.https.setChecked(False)
    box.port.setMinimum(0)
    box.port.setValue(0)
    box.apply()
    try:
        assert wg.RUNNING is not None and 'Откройте в браузере' in box.status.text()
        d = ws.WebUsersDialog()
        assert d.list.count() == 1 and 'anna' in d.list.item(0).text()
    finally:
        db.set_setting('web_enabled', '0')
        wg.apply_settings(db, tmp_path)
    assert wg.RUNNING is None


def test_remember_me_survives_restart_and_is_revoked(db):
    uid = wg.add_user(db, 'anna', 'password123', 'editor')
    g1 = wg.WebGateway(db, '127.0.0.1', 0)
    g1.start()
    try:
        c = Client(g1)
        status, _b, headers = c.request('POST', '/login', dict(login='anna', password='password123', remember='1'))
        assert status == 303 and f'Max-Age={30 * 86400}' in headers['Set-Cookie'] and 'HttpOnly' in headers['Set-Cookie']
        cookie = c.cookie
        assert db.fetchone('SELECT count(*) FROM web_tokens')[0] == 1
        assert cookie.split('=', 1)[1] not in str(db.fetchall('SELECT * FROM web_tokens'))             # в базе только хэш токена
        plain = Client(g1)
        _s, _b, h2 = plain.request('POST', '/login', dict(login='anna', password='password123'))
        assert 'Max-Age' not in h2['Set-Cookie']                                                       # без галочки — обычный сеанс до закрытия браузера
    finally:
        g1.stop()
    g2 = wg.WebGateway(db, '127.0.0.1', 0)                                                             # программу перезапустили
    g2.start()
    try:
        c2 = Client(g2)
        c2.cookie = cookie
        assert c2.request('GET', '/m/clients')[0] == 200                                               # входить заново не нужно
        wg.set_password(db, uid, 'another-pass1')                                                      # смена пароля завершает запомненные входы
        assert Client(g2).request('GET', '/m/clients')[0] == 303
        c3 = Client(g2)
        c3.request('POST', '/login', dict(login='anna', password='another-pass1', remember='1'))
        assert c3.request('GET', '/m/clients')[0] == 200
        c3.request('POST', '/logout', dict(csrf=c3.csrf('/m/clients')))
        assert db.fetchone('SELECT count(*) FROM web_tokens')[0] == 0
        c4 = Client(g2)
        c4.request('POST', '/login', dict(login='anna', password='another-pass1', remember='1'))
        wg.set_user(db, uid, active=False)
        g2.sessions.clear()
        assert c4.request('GET', '/m/clients')[0] == 303
    finally:
        g2.stop()

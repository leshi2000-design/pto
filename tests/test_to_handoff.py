"""Кнопка «Передать в ТО» в карточке «Монтаж ГСВ»: данные клиента и оборудования уходят в программу «ТО физ.лиц.»."""
import json
import os
import time

import pytest
from smetagaz import contacts_view, contract_card, counterparty_ui, main_window, workspace_view  # noqa: F401  (до подмены базы в тестах)
from smetagaz import to_handoff as th
from smetagaz.database import DatabaseManager


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    return tmp_path / 'appdata'


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'c.db')
    d.init_db()
    yield d
    d.close()


def _patch(monkeypatch, db):
    import sys
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)


def test_candidates_are_only_maintained_equipment():
    rows = [dict(kind='Счетчик', model='Гранд', serial='C1'), dict(kind='Котел', model='Navien', serial='K1'),
            dict(kind='Колонка', model='', serial=''), dict(kind='ПГ', model='Gefest', serial=''), dict(kind='Сигнализатор', model='X', serial='')]
    got = th.candidates(rows)
    assert [r['kind'] for r in got] == ['Котел', 'ПГ']                  # пустую колонку и необслуживаемое оборудование не предлагаем
    assert th.is_maintainable('котёл настенный') and th.is_maintainable('Газовая плита') and not th.is_maintainable('Регулятор')


def test_payload_and_atomic_write(appdata):
    client = dict(name='Иванов Иван', phone='375291112233; 375447778899 (жена)', address='Минск', passport='МР 1234567',
                  passport_issuer='РУВД', passport_date='2020-03-12', extra='лишнее')
    p = th.build_payload(client, [dict(kind='Котел', model='Navien', serial='S1', note='x', file_path='/etc/passwd')],
                         ' Минск, Ленина 1 ', '02-17/26', '4.9.2')
    assert p['format'] == 'to-handoff' and p['version'] == 1 and p['source'] == 'ПТО 4.9.2' and p['pto_contract'] == '02-17/26'
    assert p['client'] == {'name': 'Иванов Иван', 'phone': '375291112233; 375447778899 (жена)', 'address': 'Минск', 'passport': 'МР 1234567',
                           'issued_by': 'РУВД', 'issue_date': '2020-03-12'}
    assert p['equipment'] == [{'kind': 'Котел', 'model': 'Navien', 'serial': 'S1'}] and p['install_address'] == 'Минск, Ленина 1'   # пути к файлам не передаются
    f = th.write_payload(p)
    assert f.suffix == '.json' and f.parent == th.inbox_dir() and not list(th.inbox_dir().glob('*.tmp'))
    assert json.loads(f.read_text(encoding='utf-8'))['client']['name'] == 'Иванов Иван'
    f2 = th.write_payload(p)
    assert f2 != f                                                    # две передачи подряд не перезаписывают друг друга


def test_running_detection_and_exe_lookup(appdata, tmp_path, monkeypatch):
    assert not th.to_is_running()
    (th.inbox_dir() / th.ALIVE).write_text('1 1', encoding='utf-8')
    assert th.to_is_running() and not th.to_is_running(max_age=-1)
    os.utime(th.inbox_dir() / th.ALIVE, (time.time() - 60, time.time() - 60))
    assert not th.to_is_running()                                     # давно не обновлялся — программа закрыта
    exe = tmp_path / 'TO_fizlic.exe'
    exe.write_text('x')
    assert th.saved_exe() == ''
    th.save_exe(exe)
    assert th.saved_exe() == str(exe) and th.find_exe() == str(exe)
    exe.unlink()
    assert th.saved_exe() == ''                                       # файл удалили — запомненный путь не годится


def test_launch_failure_is_reported(tmp_path):
    assert th.launch(tmp_path / 'нет-такой-программы.exe') is False


def _card(db, monkeypatch):
    _patch(monkeypatch, db)
    from PyQt6.QtWidgets import QMessageBox
    msgs = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: msgs.append(a[2]) or 0)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: msgs.append(a[2]) or 0)
    d = contract_card.ContractCardDialog()
    d.client_form.name.setText('Иванов Иван Иванович')
    d.client_form.phone.setText('375291112233')
    d.client_form.passport.setPlainText('МР 1234567, личный номер 3010585A012PB1')
    d.client_form.passport_issuer.setText('Фрунзенский РУВД')
    d.client_form.passport_date.set_value('2010-05-20')
    d.client_form.address.setText('Минск, Ленина 3')
    d.inp_object_address.setText('Минск, Притыцкого 1')
    return d, msgs


def test_button_sends_single_boiler_without_questions(db, appdata, monkeypatch):
    d, msgs = _card(db, monkeypatch)
    d.equipment_tab.add_row(dict(kind='Счетчик', model='Гранд', serial='C1'))
    d.equipment_tab.add_row(dict(kind='Котел', model='Navien Deluxe 24K', serial='NV2410557'))
    monkeypatch.setattr(th, 'to_is_running', lambda *a, **k: True)
    monkeypatch.setattr(contract_card.ToHandoffDialog, 'exec', lambda self: pytest.fail('вопрос не нужен: котёл один'))
    assert d.to_button.text() == 'Передать в ТО'
    d.to_button.click()
    files = list(th.inbox_dir().glob('*.json'))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding='utf-8'))
    assert data['client']['name'] == 'Иванов Иван Иванович' and data['client']['passport'].startswith('МР 1234567')
    assert data['client']['issued_by'] == 'Фрунзенский РУВД' and data['client']['issue_date'] == '2010-05-20'
    assert data['client']['address'] == 'Минск, Ленина 3' and data['install_address'] == 'Минск, Притыцкого 1'
    assert data['equipment'] == [{'kind': 'Котел', 'model': 'Navien Deluxe 24K', 'serial': 'NV2410557'}]
    assert d.status.text().startswith('Передано в «ТО физ.лиц.» (Котел)')


def test_button_asks_when_several_or_none_and_launches_to(db, appdata, tmp_path, monkeypatch):
    d, msgs = _card(db, monkeypatch)
    d.equipment_tab.add_row(dict(kind='Котел', model='Navien', serial='K1'))
    d.equipment_tab.add_row(dict(kind='Колонка', model='Neva', serial='K2'))
    d.equipment_tab.add_row(dict(kind='Счетчик', model='Гранд', serial='C1'))
    seen = {}

    def fake_exec(self):
        seen['checked'] = [b.isChecked() for b in self.boxes]
        self.boxes[0].setChecked(False)                                  # сотрудник снял котёл и оставил только колонку
        return contract_card.QDialog.DialogCode.Accepted
    monkeypatch.setattr(contract_card.ToHandoffDialog, 'exec', fake_exec)
    exe = tmp_path / 'TO_fizlic.exe'
    exe.write_text('x')
    th.save_exe(exe)
    launched = []
    monkeypatch.setattr(th, 'launch', lambda e: launched.append(e) or True)
    d.to_button.click()
    assert seen['checked'] == [True, True, False]                        # по умолчанию отмечены котёл и колонка, счётчик — нет
    data = json.loads(next(th.inbox_dir().glob('*.json')).read_text(encoding='utf-8'))
    assert [e['kind'] for e in data['equipment']] == ['Колонка']
    assert launched == [str(exe)] and 'Запускаю' in d.status.text()      # программа ТО была закрыта — её запустили
    # отказ в диалоге — ничего не передаётся
    for f in th.inbox_dir().glob('*.json'):
        f.unlink()
    monkeypatch.setattr(contract_card.ToHandoffDialog, 'exec', lambda self: contract_card.QDialog.DialogCode.Rejected)
    d.to_button.click()
    assert list(th.inbox_dir().glob('*.json')) == []


def test_button_refuses_without_name_and_for_legal_customer(db, appdata, monkeypatch):
    d, msgs = _card(db, monkeypatch)
    d.client_form.name.setText('')
    d.to_button.click()
    assert msgs and 'ФИО' in msgs[-1] and list(th.inbox_dir().glob('*.json')) == []


def test_to_not_found_asks_for_exe_and_remembers(db, appdata, tmp_path, monkeypatch):
    d, msgs = _card(db, monkeypatch)
    d.equipment_tab.add_row(dict(kind='Котел', model='Navien', serial='K1'))
    monkeypatch.setattr(th, 'exe_candidates', lambda: [])
    from PyQt6.QtWidgets import QFileDialog
    exe = tmp_path / 'моя папка' / 'TO_fizlic.exe'
    exe.parent.mkdir()
    exe.write_text('x')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', staticmethod(lambda *a, **k: (str(exe), '')))
    launched = []
    monkeypatch.setattr(th, 'launch', lambda e: launched.append(e) or True)
    d.to_button.click()
    assert launched == [str(exe)] and th.saved_exe() == str(exe)         # запомнили: в следующий раз спрашивать не будем
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', staticmethod(lambda *a, **k: pytest.fail('второй раз спрашивать не нужно')))
    d.to_button.click()
    assert len(launched) == 2

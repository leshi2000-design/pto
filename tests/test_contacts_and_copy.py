import pytest
from smetagaz import contacts_view, contract_card, counterparty_ui, main_window, workspace_view  # noqa: F401  (до подмены базы в тестах)
from smetagaz.database import DatabaseManager
from smetagaz import contacts_domain as cd, gsvm_domain as md, contracts_core as cc


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


def test_contacts_domain(db):
    a = cd.save_contact(db, dict(name='Горгаз, диспетчерская', phone='104; 375291112233 (дежурный)', category='Рабочие', favorite=True))
    b = cd.save_contact(db, dict(organization='Лаборатория', phone='375172223344', category='Лаборатории'))
    with pytest.raises(ValueError):
        cd.save_contact(db, dict(phone='1'))
    assert cd.get_contact(db, b)['name'] == 'Лаборатория'
    assert [c['id'] for c in cd.listing(db)] == [a, b]                 # избранный сверху
    assert [c['id'] for c in cd.listing(db, search='дежурный')] == [a] and [c['id'] for c in cd.listing(db, category='Лаборатории')] == [b]
    # из справочников
    pid = db.execute("INSERT INTO crm.clients(name,phone,address) VALUES('Иванов И.И.','375291110000','ул. Садовая 1')").lastrowid
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='190123456', phone='375172000000', email='a@b.by', contact_person='Петров П.'))
    c1, created1 = cd.add_from_directory(db, 'client', pid)
    c2, created2 = cd.add_from_directory(db, 'legal', lid)
    assert created1 and created2 and cd.add_from_directory(db, 'client', pid) == (c1, False)
    assert cd.get_contact(db, c1)['phone'] == '375291110000' and cd.get_contact(db, c2)['organization'] == 'ООО Ромашка' and cd.get_contact(db, c2)['name'] == 'Петров П.'
    assert [c['id'] for c in cd.listing(db, linked='client')] == [c1] and [c['id'] for c in cd.listing(db, linked='legal')] == [c2] and len(cd.listing(db, linked='free')) == 2
    from smetagaz import data_services
    data_services.delete_client(db, pid)
    assert cd.get_contact(db, c1)['client_id'] is None


def test_client_copy_text():
    text = md.client_copy_text(dict(name='Иванов Иван', address='г. Минск, ул. Садовая 1', phone='375291112233; 375447778899 (жена)', passport='MC1234567', passport_issuer='Октябрьским РУВД',
                                    passport_date='2020-03-12'),
                               [dict(kind='Счетчик', model='G4', serial='111'), dict(kind='Котел', model='Viessmann Vitopend', serial='SN-777'), dict(kind='Колонка', model='X', serial='2')])
    assert text.splitlines() == ['ФИО: Иванов Иван', 'Адрес: г. Минск, ул. Садовая 1', 'Телефон: 375291112233; 375447778899 (жена)', 'Паспорт: MC1234567', 'Кем выдан: Октябрьским РУВД',
                                 'Дата выдачи: 12.03.2020', 'Котел: модель Viessmann Vitopend, серийный номер SN-777']
    assert md.client_copy_text(dict(name='А', address=''), [], 'объект') == 'ФИО: А\nАдрес: объект'
    assert 'Котел' not in md.client_copy_text(dict(name='А'), [dict(kind='Счетчик', model='1')])
    assert md.is_boiler('Котёл') and md.is_boiler('котел газовый') and not md.is_boiler('Колонка')


def test_copy_button_in_montage_card_and_edit_buttons(db, monkeypatch):
    _patch(monkeypatch, db)
    from PyQt6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: 0)
    d = contract_card.ContractCardDialog()
    d.client_form.name.setText('Иванов Иван')
    d.client_form.phone.setText('375291112233')
    d.client_form.phone.add_row('375447778899', 'жена')
    d.client_form.passport.setPlainText('MC1234567')
    d.client_form.passport_issuer.setText('РУВД')
    d.client_form.passport_date.set_value('2020-03-12')
    d.client_form.address.setText('Минск')
    d.equipment_tab.add_row(dict(kind='Котел', model='Bosch 6000', serial='SN1'))
    d.copy_client_data()
    clip = QApplication.clipboard().text()
    assert 'ФИО: Иванов Иван' in clip and '375447778899 (жена)' in clip and 'Дата выдачи: 12.03.2020' in clip and 'Котел: модель Bosch 6000, серийный номер SN1' in clip
    assert d.status.text().startswith('Скопировано')
    # карточки СМР: данные клиента и юрлица редактируются прямо из договора
    pid = db.execute("INSERT INTO crm.clients(name,phone) VALUES('Сидоров','375290000000')").lastrowid
    cd2 = counterparty_ui.ContractDialog('fl')
    counterparty_ui.populate_person_combo(cd2.cmb_person, pid)
    cd2.refresh_party_info()
    assert '375290000000' in cd2.party_info.text()

    class FakeRecord:
        def __init__(self, table, rid, parent=None):
            db.execute('UPDATE crm.clients SET phone=? WHERE id=?', ('375290000000; 375291234567 (доп)', rid))

        def exec(self):
            return 1
    monkeypatch.setattr(workspace_view, 'RecordDialog', FakeRecord)
    cd2.edit_person()
    assert '375291234567 (доп)' in cd2.party_info.text()


def test_contacts_view_and_menu(db, monkeypatch):
    _patch(monkeypatch, db)
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: 0)
    d = contacts_view.ContactDialog()
    d.name.setText('Диспетчер')
    d.phone.setText('104')
    d.phone.add_row('375291112233', 'дежурный')
    d.save()
    assert d.contact_id and cd.get_contact(db, d.contact_id)['phone'] == '104; 375291112233 (дежурный)'
    again = contacts_view.ContactDialog(d.contact_id)
    assert again.phone.text() == '104; 375291112233 (дежурный)'
    v = contacts_view.ContactsView()
    v.load_data()
    assert v.table.rowCount() == 1 and v.table.item(0, 1).text() == 'Диспетчер'
    assert dict(main_window.NAV_SECTIONS)['Клиенты'] == ['clients', 'contacts']


def test_extra_phone_persists_in_all_cards(db, monkeypatch):
    """Дополнительный телефон, добавленный при правке сохранённого договора, остаётся после закрытия и повторного открытия (Монтаж ГСВ, Монтаж ГСН, Проекты ГСВ)."""
    _patch(monkeypatch, db)
    from PyQt6.QtWidgets import QMessageBox
    from smetagaz import gsn_card, gsv_view
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: 0)
    for cls in (contract_card.ContractCardDialog, gsn_card.GsnContractDialog, gsv_view.ProjectEditDialog):
        if hasattr(cls, 'ask_folder'):
            monkeypatch.setattr(cls, 'ask_folder', lambda self, *a, **k: '')
    # Монтаж ГСВ
    d = contract_card.ContractCardDialog()
    d.client_form.name.setText('Иванов Иван')
    d.client_form.phone.setText('375291112233')
    d.inp_object.setText('Дом')
    d.save_clicked()
    cid = d.contract_id
    d = contract_card.ContractCardDialog(contract_id=cid)
    d.toggle_edit()
    d.client_form.phone.add_row('375447778899', 'доп')
    d.save_clicked()
    assert contract_card.ContractCardDialog(contract_id=cid).client_form.phone.text() == '375291112233; 375447778899 (доп)'
    # Монтаж ГСН
    g = gsn_card.GsnContractDialog()
    g.client_form.name.setText('Петров Пётр')
    g.title.setText('Объект')
    g.client_form.phone.setText('375291111111')
    assert g.save_data()
    g.client_form.phone.add_row('375292222222', 'доп')
    assert g.save_data()
    assert gsn_card.GsnContractDialog(g.contract_id).client_form.phone.text() == '375291111111; 375292222222 (доп)'
    # Проекты ГСВ
    p = gsv_view.ProjectEditDialog()
    p.client_form.name.setText('Сидоров')
    p.client_form.phone.setText('375293333333')
    p.txt_object.setText('Объект')
    p.save_clicked()
    pid = p.project_id
    p = gsv_view.ProjectEditDialog(pid)
    p.client_form.phone.add_row('375294444444', 'доп')
    p.save_clicked()
    assert gsv_view.ProjectEditDialog(pid).client_form.phone.text() == '375293333333; 375294444444 (доп)'

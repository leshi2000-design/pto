import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
from smetagaz import contracts_core as cc


@pytest.fixture
def env(tmp_path, monkeypatch):
    from smetagaz import gsv_project_domain as gd, counterparty_ui as ui, folder_ui, preflight_ui
    from smetagaz.database import DatabaseManager
    monkeypatch.setattr(gd, 'PROJECTS_DIR', tmp_path / 'p')
    monkeypatch.setattr(gd, 'TEMPLATES_DIR', tmp_path / 't')
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    import importlib, sys
    for name in ('notes_view', 'gsn_catalog', 'tasks_view', 'today_view', 'workspace_view', 'main_window', 'gsv_view', 'contract_card', 'payments_view', 'board_domain'):
        importlib.import_module('smetagaz.' + name)
    from smetagaz.database import db as singleton
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is singleton:
            monkeypatch.setattr(mod, 'db', d)
    monkeypatch.setattr(ui, 'db', d)
    import smetagaz.legal_entities_view as lev
    monkeypatch.setattr(lev, 'db', d)
    monkeypatch.setattr(preflight_ui, 'confirm', lambda *a, **k: True)
    monkeypatch.setattr(folder_ui, 'choose_folder', lambda parent, section, name, current='': (str(tmp_path / 'f' / name), True))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: print('WARN', a[2:]))
    monkeypatch.setattr(ui, 'open_file', lambda *a, **k: True)
    app = QApplication.instance() or QApplication([])
    yield d, ui
    del app
    d.close()


def test_dialogs_and_registries(env):
    db, ui = env
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789'))
    d = ui.ContractDialog('le')
    d.set_party('legal', lid)
    d.amount.setValue(1200)
    d.vat_included.setChecked(True)
    d.subject.setText('Монтаж')
    assert d.save()
    assert d.number.text().endswith('-04/' + d.number.text()[-2:])
    act = cc.save_act(db, 'le', dict(contract_id=d.contract_id, act_date='2026-03-01', amount=1200, description='Работы', signed=1))
    d.refresh_all()
    d.acts_table.selectRow(0)
    d.make('contract')
    d.make('act')
    d.make('statement')
    assert cc.doc_state(db, 'le', 'statement', act) == 'fresh'
    pid = db.execute("INSERT INTO crm.clients(name) VALUES('Петров')").lastrowid
    s = ui.ContractDialog('smr')
    s.set_party('person', pid)
    s.amount.setValue(10)
    assert s.save() and s.number.text().startswith('01-05/')
    ui.ContractDialog.open_estimate = lambda self: None
    s.create_estimate()
    assert cc.estimate_state(db, s.contract_id) == "unsynced"
    for mod in ('le', 'smr'):
        for cls in (ui.ContractsRegistry, ui.ActsRegistry, ui.TemplatesTab):
            cls(mod)
    ui.LegalClientsRegistry()
    ui.LegalClientDialog(lid)
    ui.SmrView()
    from smetagaz.legal_entities_view import LegalEntitiesView
    LegalEntitiesView()


def test_legal_customer_in_gsv_cards(env, monkeypatch):
    db, ui = env
    import smetagaz.gsv_view as gv, smetagaz.contract_card as cardm
    import sys
    from smetagaz.database import db as singleton
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is singleton:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(ui.ContractDialog, 'exec', lambda self: 1)
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789', head_name='Иванов И.И.'))
    before = db.fetchone('SELECT count(*) FROM crm.clients')[0]
    dlg = gv.ProjectEditDialog()
    dlg.customer.set_legal(lid)
    dlg.txt_object.setText('Котельная')
    dlg.spn_cost.setValue(500)
    assert dlg.save_data()
    row = db.fetchone('SELECT le_client_id,party_name,client_name,client_id FROM gsv_projects WHERE id=?', (dlg.project_id,))
    assert row == (lid, 'ООО Ромашка', '', None)
    assert db.fetchone('SELECT count(*) FROM crm.clients')[0] == before
    dlg.customer.open_contract()
    c = db.fetchone("SELECT id,client_id,amount FROM le_contracts WHERE source_type='gsv_projects' AND source_id=?", (dlg.project_id,))
    assert c[1] == lid and c[2] == 500
    assert cc.contract_from_source(db, 'gsv_projects', dlg.project_id) == (c[0], False)
    reopened = gv.ProjectEditDialog(dlg.project_id)
    assert reopened.customer.is_legal() and reopened.customer.legal_id() == lid
    card = cardm.ContractCardDialog()
    card.customer.set_legal(lid)
    card.inp_object.setText('Дом')
    assert card.save_data()
    assert db.fetchone('SELECT le_client_id,party_name,client_id FROM contracts WHERE id=?', (card.contract_id,)) == (lid, 'ООО Ромашка', None)
    assert db.fetchone('SELECT count(*) FROM crm.clients')[0] == before
    assert cc.contract_from_source(db, 'contracts', card.contract_id)[1] is True


def test_board_ui(env, monkeypatch):
    db, ui = env
    import sys
    import smetagaz.tasks_view as tv, smetagaz.today_view as today
    from smetagaz.database import db as singleton
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is singleton:
            monkeypatch.setattr(mod, 'db', db)
    from smetagaz import board_domain as bd
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    lid = cc.save_legal(db, dict(name='ООО Ромашка'))
    cid = cc.save_contract(db, 'le', dict(client_id=lid, direction='Монтажные работы', contract_date='2026-09-01', amount=10))
    view = today.TodayView()
    assert view.tabs.currentWidget() is view.board and view.tabs.tabText(0).endswith('Доска задач')
    assert not view.panel.isVisibleTo(view) and 'оплат на сегодня' in view.summary.text()
    view.board.quick.setText('Позвонить завтра #звонок !')
    view.board.quick_add()
    assert db.fetchone("SELECT count(*) FROM kanban_tasks WHERE title='Позвонить'")[0] == 1
    view.btn_calendar.setChecked(True)
    assert view.panel.isVisibleTo(view)
    view.tabs.setCurrentWidget(view.day)
    assert view.panel.isVisibleTo(view)
    view.tabs.setCurrentWidget(view.board)
    assert view.panel.isVisibleTo(view)          # выбор запомнен для вкладки доски
    view.btn_calendar.setChecked(False)
    assert not view.panel.isVisibleTo(view)
    # связь
    d = tv.TaskEditDialog(parent=view, title='Сдать акт', link=('le_contracts', cid))
    assert d.link_value() == ('le_contracts', cid)
    d.save_task()
    assert d.inp_title.text() == 'Сдать акт'
    row = db.fetchone("SELECT link_table,link_id FROM kanban_tasks WHERE title='Сдать акт'")
    assert row == ('le_contracts', cid)
    view.board.load_boards()
    # фильтры
    view.board.chk_week.setChecked(True)
    view.board.chk_week.setChecked(False)
    view.board.selected_tags = {'звонок'}
    view.board.load_boards()
    view.board.clear_tags()
    # предложения
    sd = tv.SuggestionsDialog(view)
    assert sd.items
    sd.mark(tv.Qt.CheckState.Checked)
    sd.create_checked()
    assert db.fetchone("SELECT count(*) FROM kanban_tasks WHERE auto_key<>''")[0] >= 1
    monkeypatch.setattr(tv.TaskEditDialog, 'exec', lambda self: 1)
    tv.new_task_for(view, 'le_contracts', cid)


def test_sidebar_sections_notes_and_gsn_catalog(env, monkeypatch):
    db, ui = env
    import sys
    import smetagaz.main_window as mw, smetagaz.notes_view as nv, smetagaz.gsn_catalog as gn
    from smetagaz.database import db as singleton
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is singleton:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    # дерево меню
    w = mw.MainWindow()
    names = [b.text() for b in w.tabs_buttons]
    assert names[0] == 'Сегодня' and names[-1] == 'Настройки'
    order = ['Проекты ГСВ', 'Монтаж ГСВ', 'Монтаж ГСН', 'СМР', 'Клиенты', 'Юрлица', 'Сварщики', 'Списание', 'Калькуляторы', 'Статистика']
    assert [n for n in names if n in order] == order
    assert names[-4:] == ['Справочники ГСВ', 'Справочник ГСН', 'Справочник', 'Настройки']
    assert set(w.nav_groups) == {'Услуги', 'Контрагенты', 'Дополнительно', 'Справочники'}
    w.toggle_group('Услуги', False)
    assert db.get_setting('nav_collapsed') == '["Услуги"]'
    w.switch_tab(names.index('СМР'), w.tabs_buttons[names.index('СМР')])
    assert not w.nav_groups['Услуги'][1].isHidden() and db.get_setting('nav_collapsed') == '[]'
    for i, b in enumerate(w.tabs_buttons):
        w.switch_tab(i, b)
    # заметки в «Сегодня»
    view = [v for v in w.views if getattr(v, '_tab_id', '') == 'tasks'][0]
    panel = view.notes if hasattr(view, 'notes') else None
    assert panel is not None
    panel.title.setText('Позвонить прорабу')
    panel.body.setPlainText('Уточнить сроки')
    panel.save()
    assert db.fetchone("SELECT count(*) FROM notes WHERE title='Позвонить прорабу'")[0] == 1
    panel.new_note()
    assert panel.current_link() == ('', None)
    # справочник ГСН
    cert = db.execute("INSERT INTO certificates(name,cert_number) VALUES('Сертификат ПЭ100','123')").lastrowid
    cert2 = db.execute("INSERT INTO certificates(name,cert_number) VALUES('По умолчанию','9')").lastrowid
    pid = db.execute("INSERT INTO gsn_pipelines(name,unit,certificate_id) VALUES('Труба ПЭ100 63','м',?)", (cert,)).lastrowid
    gn.add_cert_rule(db, 'pipeline_text', 'ПЭ100', cert2)
    db.execute('INSERT INTO gsn_default_certs(certificate_id) VALUES(?)', (cert2,))
    got = gn.required_certificates(db, [pid], ['Кран шаровой'])
    assert [c['id'] for c in got] == [cert, cert2]
    with pytest.raises(ValueError):
        gn.add_cert_rule(db, 'pipeline_text', 'ПЭ100', cert2)
    catalog = gn.GsnCatalogView()
    assert catalog.table.rowCount() == 1
    gn.GsnRulesDialog()

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
    for name in ('notes_view', 'gsn_catalog', 'tasks_view', 'today_view', 'workspace_view', 'main_window', 'gsv_view', 'contract_card', 'payments_view', 'board_domain', 'estimates_ui', 'estimate_editor', 'estimates_registry', 'work_breakdown_view', 'report_dialog', 'dialogs_common'):
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
    from datetime import date
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
    # справочник ГСН: независим от ГСВ
    c1 = gn.save_cert(db, dict(name='Сертификат ПЭ100', number='123', valid_to='2026-10-20'))
    c2 = gn.save_cert(db, dict(name='Общий', always=True))
    item = gn.save_item(db, dict(category='Трубопроводы', name='Труба ПЭ100 63', unit='м'), cert_ids=[c1])
    assert [c['id'] for c in gn.required_certificates(db, [item])] == [c1, c2]
    assert gn.required_certificates(db, []) == [dict(id=c2, name='Общий', number='', path='', reason='всегда')]
    assert gn.cert_state('2026-12-20', date(2026, 10, 8))[0] == 'ok' and gn.cert_state('2026-10-20', date(2026, 10, 8))[0] == 'soon' and gn.cert_state('2026-10-01', date(2026, 10, 8))[0] == 'expired'
    assert db.fetchone('SELECT count(*) FROM certificates')[0] == 0        # общий реестр сертификатов ГСВ не затронут
    with pytest.raises(ValueError):
        gn.save_cert(db, dict(name='x', valid_from='2026-02-01', valid_to='2026-01-01'))
    catalog = gn.GsnCatalogView()
    catalog.load_data()
    assert catalog.items.table.rowCount() == 1 and catalog.certs.table.rowCount() == 2
    gn.GsnItemDialog(item)
    gn.GsnCertDialog(c1)


def test_estimates_ui(env, monkeypatch, tmp_path):
    db, ui = env
    from docx import Document
    from smetagaz import estimates_domain as ed
    import smetagaz.estimates_ui as eu, smetagaz.estimate_editor as ee, smetagaz.work_breakdown_view as wb
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    pid = db.execute("INSERT INTO crm.clients(name,phone) VALUES('Петров Пётр','+375')").lastrowid
    lid = cc.save_legal(db, dict(name='ООО Ромашка'))
    cid = cc.save_contract(db, 'smr', dict(party_type='person', person_id=pid, contract_date='2026-05-01', amount=1))
    # диалог создания: по умолчанию без договора
    d = eu.NewEstimateDialog()
    d.cmb_person.setCurrentIndex(d.cmb_person.findData(pid))
    assert d.values() == ('', ('person', pid), None, False)
    d.contract = ('smr_contracts', cid)
    d.rb_contract.setChecked(True)
    assert d.values()[2] == ('smr_contracts', cid) and d.values()[3] is False
    d.chk_link.setChecked(True)
    assert d.values()[3] is True
    d.rb_none.setChecked(True)
    assert d.values() == ('', None, None, False)
    eid = ed.create_estimate(db, 'Баня', client=('person', pid))
    for name, itype, qty, price, purchase in (('Труба', 'Материал', 10, 10, 6), ('Монтаж', 'Работа', 2, 50, 30)):
        db.execute("INSERT INTO estimate_items(estimate_id,name,item_type,unit,quantity,price,sum,purchase_price) VALUES(?,?,?,?,?,?,?,?)", (eid, name, itype, 'шт', qty, price, qty * price, purchase))
    # модуль и реестр
    module = eu.EstimatesModule()
    reg = module.registry
    assert reg.table.columnCount() == 9 and reg.table.item(0, 8).text() == '— без договора —'
    reg.combo_contract.setCurrentIndex(2)
    assert reg.table.rowCount() == 0
    reg.combo_contract.setCurrentIndex(1)
    assert reg.table.rowCount() == 1
    # редактор: без начислений, договор привязывается и отвязывается
    editor = ee.EstimateEditorDialog(eid, 'Баня')
    assert not hasattr(editor, 'chk_vat') and not hasattr(editor, 'chk_social') and not hasattr(editor, 'show_item_profits')
    assert editor.grand_total == 200
    monkeypatch.setattr(ee.EstimateEditorDialog, 'pick_contract', lambda self, with_estimate, title: ('smr_contracts', cid))
    editor.link_contract()
    assert ed.contract_of(db, eid)['section'] == 'СМР' and 'Договор:' in editor.lbl_contract.text()
    editor.fill_contract_menu()
    assert [a.text() for a in editor.contract_menu.actions()][-1] == 'Отвязать договор'
    editor.unlink_contract()
    assert ed.contract_of(db, eid) is None
    ed.set_client(db, eid, 'legal', lid)
    editor.load_meta()
    assert editor.inp_client.text() == 'ООО Ромашка' and editor.inp_client.isReadOnly()
    editor.spin_total_adj.setValue(10)
    assert db.fetchone('SELECT total,client_name,party_name FROM estimates WHERE id=?', (eid,)) == (220.0, '', 'ООО Ромашка')
    # единое окно расшифровки и маржи
    dlg = wb.WorkBreakdownDialog(eid)
    assert dlg.tabs.count() == 3 and dlg.table_works.rowCount() == 1 and dlg.table_materials.rowCount() == 1 and dlg.table_summary.rowCount() == 11
    # шаблоны и теги
    tpl = tmp_path / 't.docx'
    doc = Document(); doc.add_paragraph('{{клиент}} {{итого}}'); doc.save(tpl)
    db.execute('UPDATE estimates SET prepared_by=? WHERE id=?', ('Иванов', eid))
    db.execute("INSERT INTO report_templates(kind,name,file_path) VALUES('estimates','Смета',?)", (str(tpl),))
    tab = eu.EstimateTemplatesTab()
    tab.templates.selectRow(0)
    tab.check_template()
    assert tab.status.text().startswith('Проверка пройдена')
    assert tab.tags.rowCount() >= 30 and tab.table_tags.rowCount() > 20
    tab.new_tag()
    tab.tags.item(tab.tags.rowCount() - 1, 0).setText('Сумма Работ')
    tab.save_tags()
    assert db.fetchone("SELECT count(*) FROM est_tags WHERE name='сумма_работ'")[0] == 1

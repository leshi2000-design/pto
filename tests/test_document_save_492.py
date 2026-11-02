"""Save As, cancellation, custom names and multi-folder document publication."""
from pathlib import Path
from types import SimpleNamespace
import importlib
import sqlite3

import pytest
from docx import Document
from openpyxl import Workbook, load_workbook
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QFileDialog, QApplication, QMessageBox

from smetagaz import document_save as ui_save, document_files, gsv_project_domain as gd
from smetagaz.database import DatabaseManager
from smetagaz import gsvm_docs, gsn_docs, contracts_core, orders_domain, dossier_domain, template_domain, template_engine
from test_revision_requests import setup_dossier


@pytest.fixture
def db(tmp_path, monkeypatch):
    data = tmp_path / 'data'; data.mkdir()
    db = DatabaseManager(data / 'smetagaz.db'); db.init_db()
    monkeypatch.setattr(gd, 'TEMPLATES_DIR', tmp_path / 'templates')
    monkeypatch.setattr(gsvm_docs, 'TEMPLATES_DIR', tmp_path / 'templates' / 'gsvm')
    monkeypatch.setattr(gsn_docs, 'TEMPLATES_DIR', tmp_path / 'templates' / 'gsn')
    monkeypatch.setattr(ui_save, '_last_directory', '')
    yield db
    db.close()


def records(db):
    cid = db.execute("INSERT INTO contracts(contract_number,client_name,object_name,contract_amount) VALUES('01/26','Иванов','Дом',100)").lastrowid
    nid = db.execute("INSERT INTO gsn_projects(title,contract_number,client_name,contract_amount) VALUES('Газоснабжение','02/26','Иванов',100)").lastrowid
    pid = db.execute("INSERT INTO gsv_projects(pd_number,contract_number,client_name,object_name,cost,act_date) VALUES('ПД-03/26','03/26','Иванов','Дом',100,'2026-11-01')").lastrowid
    for mod, cfg in contracts_core.MODS.items():
        db.execute(f'INSERT INTO {cfg["contracts"]}(contract_number,object_name,amount) VALUES(?,?,100)', (mod + '-04/26', 'Дом'))
    return cid, nid, pid


def test_native_save_dialog_prefills_name_and_accepts_renaming(tmp_path, monkeypatch):
    calls = []
    def accept(dialog):
        assert QThread.currentThread() == QApplication.instance().thread()
        assert dialog.acceptMode() == QFileDialog.AcceptMode.AcceptSave
        assert dialog.fileMode() == QFileDialog.FileMode.AnyFile
        assert not dialog.testOption(QFileDialog.Option.DontConfirmOverwrite)
        assert dialog.defaultSuffix() == 'docx'
        assert Path(dialog.selectedFiles()[0]).name == 'Договор_01-26.docx'
        calls.append(1)
        dialog.selectFile(str(tmp_path / 'Моё имя'))
        return QFileDialog.DialogCode.Accepted
    monkeypatch.setattr(QFileDialog, 'exec', accept)
    selected = ui_save.choose_document_path(None, tmp_path / 'Договор_01-26.docx')
    assert selected == str(tmp_path / 'Моё имя.docx')
    assert calls == [1] and not Path(selected).exists()


def test_native_save_dialog_cancel_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, 'exec', lambda self: QFileDialog.DialogCode.Rejected)
    assert ui_save.choose_document_path(None, tmp_path / 'Акт.pdf') == ''
    assert not list(tmp_path.iterdir())


def test_template_cannot_be_selected_as_output(tmp_path, monkeypatch):
    source = tmp_path / 'source.docx'; source.write_bytes(b'original template')
    answers = iter([source, tmp_path / 'copy.docx'])
    warnings = []
    def accept(dialog):
        dialog.selectFile(str(next(answers)))
        return QFileDialog.DialogCode.Accepted
    monkeypatch.setattr(QFileDialog, 'exec', accept)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    assert ui_save.choose_document_path(None, tmp_path / 'result.docx', protected=[source]) == str(tmp_path / 'copy.docx')
    assert warnings and source.read_bytes() == b'original template'


def test_batch_cancel_and_duplicate_choices_are_handled_before_writing(tmp_path, monkeypatch):
    a, b = tmp_path / 'a.docx', tmp_path / 'b.docx'
    choices = iter([str(a), str(a), ''])
    calls = []
    def choose(parent, suggested, **kwargs):
        calls.append(Path(suggested).name)
        return next(choices)
    monkeypatch.setattr(ui_save, 'choose_document_path', choose)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
    assert ui_save.choose_document_paths(None, [dict(key='a', path=a), dict(key='b', path=b)]) is None
    assert calls == ['a.docx', 'b.docx', 'b.docx']
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('module', ['gsvm', 'gsn', 'project', 'le', 'smr', 'to', 'ip', 'fl'])
def test_single_generators_honor_custom_name_and_folder_without_contract_folder(db, tmp_path, module):
    cid, nid, pid = records(db)
    destination = tmp_path / 'chosen' / module / 'Мой договор.DOCX'
    if module in ('gsvm', 'gsn', 'project'):
        domain, rid = {'gsvm': (gsvm_docs, cid), 'gsn': (gsn_docs, nid), 'project': (gd, pid)}[module]
        suggested = domain.suggested_path(db, rid, 'contract')
        assert suggested.endswith('.docx') and Path(suggested).name.startswith('Договор')
        path = domain.generate(db, rid, 'contract', destination=destination)
        assert domain.doc_path(db, rid, 'contract') == str(destination)
        old = destination.read_bytes()
        another = destination.with_name('Другая версия.docx')
        domain.generate(db, rid, 'contract', destination=another)
    else:
        assert contracts_core.suggested_path(db, module, 'contract', 1).endswith('.docx')
        path = contracts_core.generate(db, module, 'contract', 1, destination=destination)
        assert contracts_core.doc_path(db, module, 'contract', 1) == str(destination)
        old = destination.read_bytes()
        another = destination.with_name('Другая версия.docx')
        contracts_core.generate(db, module, 'contract', 1, destination=another)
    assert path == str(destination) and Document(path).paragraphs
    assert another.is_file() and destination.read_bytes() == old


def test_excel_template_controls_default_extension_and_preserves_chosen_case(db, tmp_path):
    cid, _, _ = records(db)
    template = tmp_path / 'custom.xlsx'
    wb = Workbook(); wb.active['A1'] = '{НОМЕР_ДОГОВОРА}'; wb.save(template)
    db.set_setting(gsvm_docs.template_setting('contract'), str(template))
    assert gsvm_docs.suggested_path(db, cid, 'contract').endswith('.xlsx')
    output = tmp_path / 'выбрано' / 'Моя таблица.XLSX'
    assert gsvm_docs.generate(db, cid, 'contract', destination=output) == str(output)
    assert load_workbook(output).active['A1'].value == '01/26'
    original = template.read_bytes()
    with pytest.raises(ValueError, match='шаблона'):
        gsvm_docs.generate(db, cid, 'contract', destination=template)
    assert template.read_bytes() == original


def test_order_uses_chosen_destination(db, tmp_path):
    from test_orders import make_staff, order_values
    wid, = make_staff(db, 'Иванов')
    oid = orders_domain.save_order(db, order_values(), [wid], [])
    assert Path(orders_domain.suggested_path(db, oid)).name.startswith('Наряд_')
    output = tmp_path / 'output' / 'Наряд по моему имени.docx'
    assert orders_domain.generate(db, oid, destination=output) == str(output)
    assert db.fetchone('SELECT doc_path FROM work_orders WHERE id=?', (oid,)) == (str(output),)
    assert 'Иванов' in '\n'.join(p.text for p in Document(output).paragraphs)


@pytest.mark.parametrize('module', ['gsvm', 'gsn', 'project', 'le'])
@pytest.mark.parametrize('cancel', [True, False])
def test_card_actions_always_ask_and_cancel_preserves_doc_reference(db, tmp_path, monkeypatch, module, cancel):
    cid, nid, pid = records(db)
    from smetagaz import preflight, preflight_ui
    monkeypatch.setattr(preflight_ui, 'confirm', lambda *args: True)
    monkeypatch.setattr(preflight, 'check_montage', lambda *args: [])
    monkeypatch.setattr(preflight, 'check_project', lambda *args: [])
    monkeypatch.setattr(gsn_docs, 'check', lambda *args: [])
    monkeypatch.setattr(contracts_core, 'check', lambda *args: [])
    name, cls, method, rid = {
        'gsvm': ('contract_card', 'ContractCardDialog', 'make_document', cid),
        'gsn': ('gsn_card', 'GsnContractDialog', 'make_document', nid),
        'project': ('gsv_view', 'ProjectEditDialog', 'make_document', pid),
        'le': ('counterparty_ui', 'ContractDialog', 'make', 1),
    }[module]
    mod = importlib.import_module('smetagaz.' + name)
    monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(mod, 'open_file' if module != 'project' else 'open_file_or_dir', lambda *args: None)
    output = tmp_path / 'chosen' / (module + '.docx')
    calls = []
    def choose(parent, suggested, **kwargs):
        calls.append(Path(suggested).name)
        assert kwargs.get('protected')
        return '' if cancel else str(output)
    monkeypatch.setattr(ui_save, 'choose_document_path', choose)
    status = SimpleNamespace(setText=lambda text: None)
    fake = SimpleNamespace(contract_id=rid, project_id=rid, is_new=False, is_editing_enabled=False,
                           ensure_saved=lambda: True, ensure_folder=lambda: pytest.fail('must not require a contract folder'),
                           ref_for=lambda kind: rid, mod='le', refresh_docs=lambda: None, refresh_all=lambda: None,
                           status=status, save_status=status)
    getattr(getattr(mod, cls), method)(fake, 'contract')
    assert len(calls) == 1
    assert output.exists() is (not cancel)
    if module == 'le':
        stored = contracts_core.doc_path(db, 'le', 'contract', rid)
    else:
        domain = {'gsvm': gsvm_docs, 'gsn': gsn_docs, 'project': gd}[module]
        stored = domain.doc_path(db, rid, 'contract')
    assert stored == ('' if cancel else str(output))


def test_dossier_can_save_each_document_to_different_folders_and_rename(db, tmp_path):
    _, did, folder = setup_dossier(db, tmp_path)
    plan = dossier_domain.planned_documents(db, did)
    destinations = {job['key']: str(tmp_path / job['key'] / ('Моё_' + job['key'] + '.docx')) for job in plan}
    result = dossier_domain.generate(db, did, destinations=destinations)
    assert result['changed'] == 2
    stored = dict(db.fetchall('SELECT slot,file_path FROM dossier_files WHERE dossier_id=?', (did,)))
    assert stored == destinations and not list(folder.glob('ИД_*'))
    assert all(Path(p).is_file() for p in destinations.values())
    another = {key: str(tmp_path / 'new names' / (key + '.docx')) for key in destinations}
    dossier_domain.generate(db, did, destinations=another)
    assert all(Path(p).is_file() for p in destinations.values())
    assert dict(db.fetchall('SELECT slot,file_path FROM dossier_files WHERE dossier_id=?', (did,))) == another


def test_dossier_cancel_keeps_selection_and_writes_nothing(db, tmp_path, monkeypatch):
    _, did, _ = setup_dossier(db, tmp_path)
    import smetagaz.dossier_view as view
    monkeypatch.setattr(view, 'db', db)
    before = db.fetchall('SELECT slot FROM dossier_selection WHERE dossier_id=? ORDER BY slot', (did,))
    monkeypatch.setattr(ui_save, 'choose_document_paths', lambda *args: None)
    dialog = view.DossierDialog(did)
    dialog.generate()
    assert dialog.future is None
    assert db.fetchall('SELECT slot FROM dossier_selection WHERE dossier_id=? ORDER BY slot', (did,)) == before
    assert db.fetchone('SELECT count(*) FROM dossier_files') == (0,)
    assert not list(tmp_path.rglob('.pto-document-*'))
    dialog.reject()


def test_template_batch_register_uses_chosen_names(db, tmp_path):
    _, did, folder = setup_dossier(db, tmp_path)
    data = dossier_domain.row(db, did); rid = data['owner_id']
    register = tmp_path / 'registry.docx'; doc = Document(); doc.add_paragraph('{{реестр}}'); doc.save(register)
    template_domain.save_template(db, 'gsn_projects', 'register', str(register), 'Реестр')
    plan = template_engine.planned_documents(db, 'gsn_projects', rid, ['title', 'register'], False)
    destinations = {job['key']: str(tmp_path / ('chosen ' + job['key']) / ('Пользователь_' + job['key'] + '.docx')) for job in plan}
    paths = template_engine.generate(db, 'gsn_projects', rid, ['title', 'register'], False, destinations=destinations)
    assert set(paths) == set(destinations.values())
    assert Path(destinations['title']).name in Document(destinations['register']).paragraphs[0].text
    assert set(r[0] for r in db.fetchall('SELECT file_path FROM executive_generated')) == set(paths)


def test_batch_rejects_overwriting_other_source(db, tmp_path):
    _, did, _ = setup_dossier(db, tmp_path)
    plan = dossier_domain.planned_documents(db, did)
    original = {str(job['source']): Path(job['source']).read_bytes() for job in plan}
    choices = {job['key']: str(plan[-1]['source']) for job in plan}
    with pytest.raises(ValueError):
        dossier_domain.generate(db, did, destinations=choices)
    assert all(Path(path).read_bytes() == data for path, data in original.items())
    assert db.fetchone('SELECT count(*) FROM dossier_files') == (0,)


def test_publication_failure_restores_files_across_folders(tmp_path, monkeypatch):
    a = tmp_path / 'A' / 'first.docx'; a.parent.mkdir(); a.write_bytes(b'old A')
    b = tmp_path / 'B' / 'second.docx'; b.parent.mkdir(); b.write_bytes(b'old B')
    original_replace = document_files.os.replace
    def replace(source, destination):
        assert Path(source).parent.parent == Path(destination).parent
        original_replace(source, destination)
    monkeypatch.setattr(document_files.os, 'replace', replace)
    def record(hashes):
        assert a.read_bytes() == b'new A' and b.read_bytes() == b'new B'
        raise sqlite3.IntegrityError('record failed')
    with pytest.raises(sqlite3.IntegrityError):
        document_files.publish_files([(a, lambda output: output.write_bytes(b'new A')), (b, lambda output: output.write_bytes(b'new B'))], record)
    assert a.read_bytes() == b'old A' and b.read_bytes() == b'old B'
    assert not list(tmp_path.rglob('.pto-document-*'))

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import pytest
from smetagaz import security, backup
from smetagaz.database import DatabaseManager, parse_tabs_config, safe_font_size


def test_decrypt_wrong_password_keeps_existing_file(tmp_path):
    src = tmp_path / 'a.zip'; src.write_bytes(b'data' * 1000)
    enc = tmp_path / 'a.sgb'
    security.encrypt_backup(src, enc, 'correct-password-1')
    assert not list(tmp_path.glob('*.tmp'))
    target = tmp_path / 'out.zip'; target.write_bytes(b'precious')
    with pytest.raises(ValueError):
        security.decrypt_backup(enc, target, 'wrong-password-12')
    assert target.read_bytes() == b'precious' and not list(tmp_path.glob('*.tmp'))
    security.decrypt_backup(enc, target, 'correct-password-1')
    assert target.read_bytes() == b'data' * 1000


def test_encrypt_failure_keeps_old_file(tmp_path):
    enc = tmp_path / 'x.sgb'; enc.write_bytes(b'old')
    with pytest.raises(Exception):
        security.encrypt_backup(tmp_path / 'missing.zip', enc, 'correct-password-1')
    assert enc.read_bytes() == b'old' and not list(tmp_path.glob('*.tmp'))


def test_backup_hides_offsite_password_and_posix_manifest(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    d.set_setting('offsite_password', 'super-secret-password'); d.set_setting('offsite_enabled', '1')
    (tmp_path / 'attachments' / 'sub').mkdir(parents=True); (tmp_path / 'attachments' / 'sub' / 'f.txt').write_text('x')
    manifest = backup.create_backup(d, tmp_path / 'b.zip')
    assert all('\\' not in name for name in manifest['files']) and 'attachments/sub/f.txt' in manifest['files']
    assert d.get_setting('offsite_password') == 'super-secret-password' and d.get_setting('offsite_enabled') == '1'
    restored = tmp_path / 'restored'
    backup.restore_backup(tmp_path / 'b.zip', restored)
    r = DatabaseManager(restored / 'smetagaz.db')
    assert r.get_setting('offsite_password') == '' and r.get_setting('offsite_enabled') == '0'
    r.close(); d.close()


def test_tabs_config_and_font_size_are_safe():
    assert parse_tabs_config('null') == [] and parse_tabs_config('{"a":1}') == [] and parse_tabs_config('not json') == []
    tabs = parse_tabs_config(json.dumps([1, None, {'id': 'a', 'name': 'A', 'visible': 'x'}, {'id': 'a'}, {'id': 5}, {'id': 'b'}]))
    assert [t['id'] for t in tabs] == ['a', 'b'] and tabs[0]['visible'] == 1
    assert safe_font_size('abc') == 10 and safe_font_size('99') == 20 and safe_font_size('11.5') == 11


def test_dark_theme_fix_is_reversible():
    from PyQt6.QtWidgets import QApplication, QLabel
    from smetagaz import theme
    app = QApplication.instance() or QApplication([])
    label = QLabel('x'); label.setStyleSheet('color: #605E5C;')
    theme._fix_widget(label, True)
    assert '#C8C6C4' in label.styleSheet()
    theme._fix_widget(label, False)
    assert label.styleSheet() == 'color: #605E5C;'
    a, b = theme._arrow_files('#123456'), theme._arrow_files('#123456')
    assert a == b and 'smetagaz-theme-' in a['down']

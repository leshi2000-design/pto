"""File references in ordinary application tables, including composite-key document tables.

New modules using these column names automatically participate in backup/restore.
Settings with template paths are handled separately; folder_root_* are suggestions,
not individual contract folders, and are reset on restore.
"""
from pathlib import Path

FILE_COLUMNS = frozenset({'file_path', 'tu_path', 'custom_contract_path', 'doc_path'})
FOLDER_COLUMNS = frozenset({'folder', 'folder_path', 'project_folder', 'contract_folder'})
MANAGED_FOLDERS = ('projects', 'templates', 'attachments', 'certificates_storage')


def quote(name):
    return '"' + str(name).replace('"', '""') + '"'


def fields(connection):
    """Yield (table, column) from the snapshot schema, never from a network request."""
    tables = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for table, sql in tables:
        if not sql or 'VIRTUAL TABLE' in sql.upper():
            continue
        for column in connection.execute(f'PRAGMA table_info({quote(table)})'):
            if column[1] in FILE_COLUMNS | FOLDER_COLUMNS:
                yield table, column[1]


def rebase(connection, stage, destination):
    """Resolve archived relative references against the final restored location."""
    for table, column in fields(connection):
        for rowid, value in connection.execute(f'SELECT rowid,{quote(column)} FROM {quote(table)}').fetchall():
            if not value:
                continue
            path = Path(str(value).replace('\\', '/'))
            if not path.is_absolute() and (stage / path).resolve().is_relative_to(stage.resolve()) and (stage / path).exists():
                connection.execute(f'UPDATE {quote(table)} SET {quote(column)}=? WHERE rowid=?', (str(destination / path), rowid))
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone():
        for key, value in connection.execute("SELECT key,value FROM settings WHERE key LIKE '%template%'").fetchall():
            path = Path(str(value or '').replace('\\', '/'))
            if value and not path.is_absolute() and (stage / path).resolve().is_relative_to(stage.resolve()) and (stage / path).is_file():
                connection.execute('UPDATE settings SET value=? WHERE key=?', (str(destination / path), key))
        connection.execute("UPDATE settings SET value='' WHERE key GLOB 'folder_root_*'")

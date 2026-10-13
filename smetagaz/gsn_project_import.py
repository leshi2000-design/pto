"""Служебная миграция «Монтаж ГСН»: поля даты акта и отметки «Акт подписан»."""


def migrate(db):
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(gsn_projects)')}
    for name, ddl in (('act_date', "TEXT DEFAULT ''"), ('act_signed', 'INTEGER DEFAULT 0')):
        if name not in cols:
            db.execute(f'ALTER TABLE gsn_projects ADD COLUMN {name} {ddl}')

"""
Модуль "Юрлица": свои клиенты-организации, договоры по трём направлениям
(монтаж, техобслуживание, проверка дымовых/вентиляционных каналов) и акты
по ним, плюс отдельный журнал регистрации исходящей документации.

Намеренно не связан со сметами и общей базой клиентов-физлиц: стоимость
работ задаётся одной цифрой (с отметкой, включён ли НДС), без разбивки.
"""

DIRECTIONS = (
    "Монтажные работы",
    "Техническое обслуживание",
    "Проверка дымовых и вентиляционных каналов",
)

STATUSES = ("Действует", "Завершён", "Расторгнут")


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS le_clients(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        unp TEXT DEFAULT '',
        address TEXT DEFAULT '',
        contact_person TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        note TEXT DEFAULT ''
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS le_contracts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        direction TEXT NOT NULL DEFAULT 'Монтажные работы',
        contract_number TEXT DEFAULT '',
        contract_date TEXT DEFAULT '',
        client_id INTEGER REFERENCES le_clients(id) ON DELETE RESTRICT,
        object_name TEXT DEFAULT '',
        amount REAL DEFAULT 0.0,
        vat_included INTEGER DEFAULT 0,
        status TEXT DEFAULT 'Действует',
        note TEXT DEFAULT ''
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS le_acts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER NOT NULL REFERENCES le_contracts(id) ON DELETE CASCADE,
        act_number TEXT DEFAULT '',
        act_date TEXT DEFAULT '',
        amount REAL DEFAULT 0.0,
        vat_included INTEGER DEFAULT 0,
        description TEXT DEFAULT '',
        note TEXT DEFAULT ''
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS le_outgoing(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reg_number TEXT DEFAULT '',
        reg_date TEXT DEFAULT '',
        recipient TEXT DEFAULT '',
        subject TEXT DEFAULT '',
        client_id INTEGER REFERENCES le_clients(id) ON DELETE SET NULL,
        note TEXT DEFAULT ''
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_le_contracts_client ON le_contracts(client_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_le_contracts_direction ON le_contracts(direction)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_le_acts_contract ON le_acts(contract_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_le_outgoing_client ON le_outgoing(client_id)")


def next_outgoing_number(db):
    """A plain incrementing suggestion; the field stays freely editable."""
    return str((db.fetchone("SELECT count(*) FROM le_outgoing")[0] or 0) + 1)

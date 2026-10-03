"""
Менеджер SQLite с транзакциями, вложенными SAVEPOINT и сериализованным доступом.
"""
import threading
import sqlite3
import json
from contextlib import contextmanager

from .config import DB_NAME

class DatabaseManager:
    def __init__(self, db_name=DB_NAME):
        self._lock = threading.RLock()
        self._init_connection(db_name)

    def _init_connection(self, db_name):
        self.db_name = str(db_name)
        self.conn = sqlite3.connect(self.db_name, timeout=20, check_same_thread=False)
        self.conn.isolation_level = None
        self.conn.create_function("LOWER", 1, lambda s: str(s or "").casefold(), deterministic=True)
        self.conn.create_function("norm", 1, lambda s: str(s or "").strip().casefold(), deterministic=True)
        self.conn.execute("PRAGMA busy_timeout=20000")
        self.conn.execute("PRAGMA journal_mode = DELETE")
        self.conn.execute("PRAGMA synchronous = FULL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        try:
            __import__('os').chmod(self.db_name,0o600)
        except OSError:
            pass

    @contextmanager
    def transaction(self):
        """Контекстный менеджер для безопасных транзакций."""
        with self._lock:
            nested = self.conn.in_transaction
            name = "sp_" + __import__("uuid").uuid4().hex
            self.conn.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
            try:
                yield self.conn.cursor()
                self.conn.execute(f"RELEASE {name}" if nested else "COMMIT")
            except BaseException:
                if self.conn.in_transaction:
                    self.conn.execute(f"ROLLBACK TO {name}" if nested else "ROLLBACK")
                    if nested: self.conn.execute(f"RELEASE {name}")
                raise

    def execute(self, query, params=()):
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            return cursor

    def executemany(self, query, seq_of_params):
        with self._lock:
            cursor = self.conn.cursor()
            cursor.executemany(query, seq_of_params)
            return cursor

    def fetchone(self, query, params=()):
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()

    def fetchall(self, query, params=()):
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()

    def get_setting(self, key, default=""):
        row = self.fetchone("SELECT value FROM settings WHERE key=?", (key,))
        if row and row[0] is not None:
            return str(row[0])
        return default

    def set_setting(self, key, value):
        self.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))

    def _init_schema(self):
        # Legacy databases are retained intact; new schemas already have FK.
        # Orphan records are reported by integrity checks, never silently dropped.
        with self._lock:
            c = self.conn.cursor()

            c.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, parent_id INTEGER)")
            c.execute("CREATE TABLE IF NOT EXISTS estimate_folders (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, parent_id INTEGER)")
            c.execute("CREATE TABLE IF NOT EXISTS materials (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, name TEXT, unit TEXT, price REAL, url TEXT, note TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS estimates (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, date TEXT, total REAL)")
            c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")

            c.execute("""CREATE TABLE IF NOT EXISTS estimate_items (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, estimate_id INTEGER, name TEXT, unit TEXT, 
                            quantity REAL, price REAL, sum REAL, item_type TEXT DEFAULT 'Материал', sort_order INTEGER DEFAULT 0,
                            FOREIGN KEY(estimate_id) REFERENCES estimates(id) ON DELETE CASCADE
                         )""")

            c.execute("""CREATE TABLE IF NOT EXISTS payments (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, estimate_id INTEGER, amount REAL, date TEXT,
                            FOREIGN KEY(estimate_id) REFERENCES estimates(id) ON DELETE CASCADE
                         )""")

            c.execute("""CREATE TABLE IF NOT EXISTS attachments (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, estimate_id INTEGER, file_name TEXT, file_path TEXT,
                            FOREIGN KEY(estimate_id) REFERENCES estimates(id) ON DELETE CASCADE
                         )""")

            c.execute("""CREATE TABLE IF NOT EXISTS contracts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, estimate_id INTEGER UNIQUE,
                            contract_number TEXT DEFAULT '', contract_date TEXT DEFAULT '', object_name TEXT DEFAULT '', 
                            client_address TEXT DEFAULT '', passport_series_number TEXT DEFAULT '', passport_issued_by TEXT DEFAULT '',
                            passport_issue_date TEXT DEFAULT '', work_start_date TEXT DEFAULT '', work_end_date TEXT DEFAULT '', 
                            acceptance_act_date TEXT DEFAULT '', contract_amount REAL DEFAULT 0.0,
                            FOREIGN KEY(estimate_id) REFERENCES estimates(id) ON DELETE CASCADE
                         )""")

            c.execute("""CREATE TABLE IF NOT EXISTS contract_equipment (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, contract_id INTEGER,
                            equipment_name TEXT DEFAULT '', certificate_number TEXT DEFAULT '', 
                            note TEXT DEFAULT '', linked_cert_id INTEGER,
                            FOREIGN KEY(contract_id) REFERENCES contracts(id) ON DELETE CASCADE
                         )""")

            c.execute("""CREATE TABLE IF NOT EXISTS gsv_projects (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, pd_number TEXT UNIQUE, seq_num INTEGER, year_num INTEGER,
                            object_name TEXT, address TEXT, client_name TEXT, phone TEXT, passport TEXT, contract_number TEXT, 
                            contract_date TEXT, due_date TEXT, act_date TEXT, tu_path TEXT, work_status TEXT, client_status TEXT, 
                            attachments TEXT, cost REAL DEFAULT 250.0, project_folder TEXT, custom_contract_path TEXT, notes TEXT
                         )""")
            c.execute("""CREATE TABLE IF NOT EXISTS kanban_tasks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT, status TEXT DEFAULT 'todo',
                            is_archived INTEGER DEFAULT 0, created_at TEXT, urgency TEXT DEFAULT 'Обычная'
                         )""")
            c.execute("""CREATE TABLE IF NOT EXISTS calendar_events (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, event_date TEXT, event_time TEXT, description TEXT
                         )""")
            c.execute("CREATE TABLE IF NOT EXISTS certificate_folders (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, parent_id INTEGER)")
            c.execute("CREATE TABLE IF NOT EXISTS certificates (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, cert_number TEXT, valid_to TEXT, file_path TEXT, folder_id INTEGER)")

            c.execute("PRAGMA table_info(estimates)")
            est_cols = [row[1] for row in c.fetchall()]
            if "paid" not in est_cols: c.execute("ALTER TABLE estimates ADD COLUMN paid REAL DEFAULT 0.0")
            if "payment_date" not in est_cols: c.execute("ALTER TABLE estimates ADD COLUMN payment_date TEXT DEFAULT ''")
            if "client_name" not in est_cols: c.execute("ALTER TABLE estimates ADD COLUMN client_name TEXT DEFAULT ''")
            if "client_phone" not in est_cols: c.execute("ALTER TABLE estimates ADD COLUMN client_phone TEXT DEFAULT ''")
            if "statuses" not in est_cols: c.execute("ALTER TABLE estimates ADD COLUMN statuses TEXT DEFAULT 'Предварительная смета'")
            if "folder_id" not in est_cols: c.execute("ALTER TABLE estimates ADD COLUMN folder_id INTEGER")
            for col, d_type, d_val in [("has_overhead", "INTEGER", "0"), ("overhead_pct", "REAL", "15.0"), ("has_profit", "INTEGER", "0"), ("profit_pct", "REAL", "10.0"), ("has_vat", "INTEGER", "0"), ("vat_pct", "REAL", "20.0"), ("has_social", "INTEGER", "0"), ("social_pct", "REAL", "34.6"), ("mat_adj_pct", "REAL", "0.0"), ("work_adj_pct", "REAL", "0.0"), ("total_adj_pct", "REAL", "0.0")]:
                if col not in est_cols: c.execute(f"ALTER TABLE estimates ADD COLUMN {col} {d_type} DEFAULT {d_val}")

            c.execute("PRAGMA table_info(estimate_items)")
            items_cols = [row[1] for row in c.fetchall()]
            if "item_type" not in items_cols: c.execute("ALTER TABLE estimate_items ADD COLUMN item_type TEXT DEFAULT 'Материал'")
            if "sort_order" not in items_cols: c.execute("ALTER TABLE estimate_items ADD COLUMN sort_order INTEGER DEFAULT 0")
            if "purchase_price" not in items_cols: c.execute("ALTER TABLE estimate_items ADD COLUMN purchase_price REAL DEFAULT 0.0")
            # Work-cost breakdown is snapshotted per line at add-time (like price/purchase_price
            # already are), so a later edit to the catalog formula never changes an existing estimate.
            for col in ("labor_hours", "hourly_rate", "overhead_pct", "profit_pct", "other_costs"):
                if col not in items_cols: c.execute(f"ALTER TABLE estimate_items ADD COLUMN {col} REAL DEFAULT 0.0")

            c.execute("PRAGMA table_info(materials)")
            mat_cols = [row[1] for row in c.fetchall()]
            if "item_type" not in mat_cols: c.execute("ALTER TABLE materials ADD COLUMN item_type TEXT DEFAULT 'Материал'")
            if "purchase_price" not in mat_cols: c.execute("ALTER TABLE materials ADD COLUMN purchase_price REAL DEFAULT 0.0")
            # Formula-driven price for catalog "Работа" items; see work_pricing.compute_work_price.
            for col in ("labor_hours", "hourly_rate", "overhead_pct", "profit_pct", "other_costs"):
                if col not in mat_cols: c.execute(f"ALTER TABLE materials ADD COLUMN {col} REAL DEFAULT 0.0")

            c.execute("PRAGMA table_info(contract_equipment)")
            ce_cols = [row[1] for row in c.fetchall()]
            if "linked_cert_id" not in ce_cols: c.execute("ALTER TABLE contract_equipment ADD COLUMN linked_cert_id INTEGER")

            c.execute("PRAGMA table_info(certificates)")
            cert_cols = [row[1] for row in c.fetchall()]
            if "folder_id" not in cert_cols: c.execute("ALTER TABLE certificates ADD COLUMN folder_id INTEGER")

            c.execute("CREATE INDEX IF NOT EXISTS idx_mat_cat ON materials(category_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_mat_name ON materials(name)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_est_items ON estimate_items(estimate_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_est_date ON estimates(date)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_contract_estimate ON contracts(estimate_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_contract_equipment ON contract_equipment(contract_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_gsv_year_seq ON gsv_projects(year_num, seq_num)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_gsv_statuses ON gsv_projects(work_status, client_status)")

            default_tabs = [
                {"id": "tasks", "name": "Задачи и Календарь", "visible": 1},
                {"id": "estimates", "name": "Реестр смет", "visible": 1},
                {"id": "contracts", "name": "ГСВ", "visible": 1},
                {"id": "gsv", "name": "Проекты ГСВ", "visible": 1},
                {"id": "gsn", "name": "Проекты ГСН", "visible": 1},
                {"id": "legal_entities", "name": "Юрлица", "visible": 1},
                {"id": "exec", "name": "Исполнительная док.", "visible": 1},
                {"id": "materials", "name": "Справочник", "visible": 1},
                {"id": "welders", "name": "Сварщики", "visible": 1},
                {"id": "calculators", "name": "Калькуляторы", "visible": 1},
                {"id": "writeoff", "name": "Списание", "visible": 1},
                {"id": "stats", "name": "Статистика", "visible": 1},
                {"id": "settings", "name": "Настройки", "visible": 1}
            ]

            defaults = [
                ('accent_color', '#0284C7'), ('is_dark', '0'), ('font_family', 'Segoe UI'),
                ('font_size', '10'), ('last_name_selector', 'h1'), ('last_price_selector', '.price'),
                ('def_overhead_pct', '15.0'), ('def_profit_pct', '10.0'),
                ('def_vat_pct', '20.0'), ('def_social_pct', '34.6'),
                ('export_font', 'Segoe UI'), ('export_font_size', '13'),
                ('export_company_name', 'ООО "ГазМонтаж"'),
                ('export_excel_template', ''), ('export_word_template', ''),
                ('app_name', 'СМЕТА-ГАЗ 2.4'), ('tabs_config', json.dumps(default_tabs))
            ]
            c.executemany("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", defaults)

    def init_db(self):
        # Save original databases before the first schema upgrade.
        from pathlib import Path
        from datetime import datetime
        has_schema=self.fetchone("SELECT 1 FROM sqlite_master WHERE type='table' AND name='estimates'")
        has_settings=self.fetchone("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'")
        version=self.get_setting('schema_version','') if has_settings else ''
        if has_schema and version!='8':
            folder=Path(self.db_name).parent/'backups'/('before_upgrade_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            folder.mkdir(parents=True)
            with sqlite3.connect(folder/'smetagaz.db') as target:
                self.conn.backup(target)
            clients=Path(self.db_name).with_name('clients.db')
            if clients.exists():
                with sqlite3.connect(clients) as source, sqlite3.connect(folder/'clients.db') as target:source.backup(target)
        with self.transaction():
            self._init_schema()
        from .data_services import initialize
        initialize(self)
        # 2.4: "Реестр договоров" renamed to "ГСВ" (внутреннее газоснабжение). Only rename the tab
        # if it still has the old default label, so a user's own custom rename is left alone.
        try:
            tabs_data=json.loads(self.get_setting("tabs_config","[]"))
        except (ValueError, TypeError):
            tabs_data=[]
        renamed=False
        for tab in tabs_data:
            if tab.get("id")=="contracts" and tab.get("name")=="Реестр договоров":
                tab["name"]="ГСВ";renamed=True
        if renamed:self.set_setting("tabs_config",json.dumps(tabs_data))
        self.set_setting("schema_version","8")
        if self.get_setting("app_name") in ("СМЕТА-ГАЗ 2.0","СМЕТА-ГАЗ 2.1","СМЕТА-ГАЗ 2.2","СМЕТА-ГАЗ 2.3"):self.set_setting("app_name","СМЕТА-ГАЗ 2.4")

    def close(self):
        with self._lock:
            self.conn.close()


db = DatabaseManager()

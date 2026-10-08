"""Нагрузочный замер на ~10 000 записей: python3 tests/benchmark_large.py [масштаб]. Результаты — в миллисекундах."""
import json
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(scale=1.0):
    from smetagaz.database import DatabaseManager, db as singleton
    import bigdata
    with tempfile.TemporaryDirectory() as tmp:
        d = DatabaseManager(Path(tmp) / 'smetagaz.db')
        d.init_db()
        t = time.perf_counter()
        counts = bigdata.generate(d, scale)
        generated = time.perf_counter() - t
        results = {}

        def measure(name, fn, repeat=1):
            fn()
            start = time.perf_counter()
            for _ in range(repeat):
                fn()
            results[name] = round((time.perf_counter() - start) / repeat * 1000, 1)

        from smetagaz import board_domain as board, acts_statement, agenda_domain as agenda, contracts_core as cc, integrity, estimates_domain as ed
        from smetagaz.data_services import search
        today = date(2026, 10, 1)
        measure('сводка «Сегодня»', lambda: board.summary(d, today))
        measure('предложения задач', lambda: board.suggestions(d, today))
        measure('ведомость актов (Юрлица)', lambda: acts_statement.statement(d, 'le_contracts', 2026, 9))
        measure('ведомость актов (Монтаж ГСВ)', lambda: acts_statement.statement(d, 'contracts', 2026, 9))
        measure('календарь: месяц', lambda: agenda.events_between(d, date(2026, 9, 1), date(2026, 9, 30)))
        measure('глобальный поиск', lambda: search(d, 'Компания 1500'), 5)
        measure('проверка базы', lambda: integrity.check(d))
        measure('смета: итог', lambda: ed.totals(d, 5), 20)
        measure('смета: маржа', lambda: ed.margin_summary(d, 5), 20)
        # интерфейс (реестры)
        from PyQt6.QtWidgets import QApplication
        import importlib
        app = QApplication.instance() or QApplication([])
        for name in ('counterparty_ui', 'estimates_registry', 'gsv_view', 'notes_view', 'today_view', 'estimates_ui', 'legal_entities_view', 'dossier_client'):
            try:
                importlib.import_module('smetagaz.' + name)
            except ModuleNotFoundError:
                pass
        for name, mod in list(sys.modules.items()):
            if name.startswith('smetagaz') and getattr(mod, 'db', None) is singleton:
                mod.db = d
        import smetagaz.counterparty_ui as ui
        import smetagaz.estimates_registry as er
        import smetagaz.notes_view as nv
        import smetagaz.today_view as tv
        start = time.perf_counter(); reg = ui.ContractsRegistry('le'); results['реестр «Юрлица»: открытие'] = round((time.perf_counter() - start) * 1000, 1)
        measure('реестр «Юрлица»: поиск', lambda: (reg.search.setText('Компания 7'), reg.search.setText('')))
        start = time.perf_counter(); reg2 = ui.ContractsRegistry('smr'); results['реестр «СМР»: открытие'] = round((time.perf_counter() - start) * 1000, 1)
        start = time.perf_counter(); ui.ActsRegistry('le'); results['акты «Юрлица»: открытие'] = round((time.perf_counter() - start) * 1000, 1)
        start = time.perf_counter(); ui.LegalClientsRegistry(); results['справочник юрлиц: открытие'] = round((time.perf_counter() - start) * 1000, 1)
        start = time.perf_counter(); er.EstimatesView(); results['реестр смет: открытие'] = round((time.perf_counter() - start) * 1000, 1)
        start = time.perf_counter(); nv.NotesPanel(); results['заметки: открытие'] = round((time.perf_counter() - start) * 1000, 1)
        start = time.perf_counter(); tv.TodayView(); results['«Сегодня»: открытие'] = round((time.perf_counter() - start) * 1000, 1)
        if hasattr(sys.modules.get('smetagaz.dossier_client'), 'client_dossier'):
            dm = sys.modules['smetagaz.dossier_client']
            cid = d.fetchone('SELECT client_id FROM estimates WHERE client_id IS NOT NULL LIMIT 1')[0]
            measure('досье клиента', lambda: dm.client_dossier(d, 'person', cid), 5)
        from smetagaz.backup import create_backup, restore_backup
        start = time.perf_counter(); create_backup(d, Path(tmp) / 'b.zip'); results['резервная копия'] = round((time.perf_counter() - start) * 1000, 1)
        start = time.perf_counter(); restore_backup(Path(tmp) / 'b.zip', Path(tmp) / 'r'); results['восстановление'] = round((time.perf_counter() - start) * 1000, 1)
        size = round(os.path.getsize(Path(tmp) / 'smetagaz.db') / 1e6, 1)
        print(json.dumps(dict(записей=counts, генерация_сек=round(generated, 1), размер_базы_МБ=size), ensure_ascii=False))
        width = max(len(k) for k in results)
        for k, v in sorted(results.items(), key=lambda kv: -kv[1]):
            print(f'{k:<{width}}  {v:>9.1f} мс')
        d.close()


if __name__ == '__main__':
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 1.0)

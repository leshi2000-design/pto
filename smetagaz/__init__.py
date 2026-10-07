"""
СМЕТА-ГАЗ — приложение для составления и учёта строительных смет.

Структура пакета:
    config.py             — константы, настройка логирования
    database.py           — DatabaseManager (транзакции и миграции SQLite)
    services.py           — AutoBackupService (полный автобэкап баз и документов)
    widgets.py            — переиспользуемые табличные виджеты (SmartTableManager)
    dialogs_common.py     — общие диалоги
    scraper.py            — парсинг цены
    material_card.py      — карточка материала
    materials_view.py     — вкладка "Справочник"
    contract_card.py      — карточка договора
    contracts_registry.py — вкладка "ГСВ"
    estimate_editor.py    — редактор сметы
    estimates_registry.py — вкладка "Реестр смет"
    gsv_view.py           — вкладка "Проекты ГСВ"
    executive_view.py     — вкладка "Исполнительная док." (сертификаты)
    tasks_view.py         — вкладка "Задачи и Календарь"
    extra_views.py        — новые модули (ГСН, Сварщики, Калькуляторы, Списание)
    statistics_view.py    — вкладка "Статистика"
    settings_view.py      — вкладка "Настройки"
    main_window.py        — главное окно и точка входа main()
"""
__version__ = "2.7.0"

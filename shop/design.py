"""Shared visual theme for the application and its dialogs."""
THEME = '''
QWidget { font-family: "Segoe UI", "DejaVu Sans", sans-serif; font-size: 13px; color: #25364b; }
QMainWindow, QDialog { background: #f2f5fa; }
QWidget#Sidebar { background: #142b43; border-radius: 18px; }
QLabel#Brand { color: white; font-size: 25px; font-weight: 700; }
QLabel#BrandNote { color: #98b1c8; font-size: 12px; }
QListWidget#Navigation { background: transparent; border: none; outline: none; color: #c9d7e6; }
QListWidget#Navigation::item { padding: 10px 8px; margin: 2px 0; border-radius: 9px; }
QListWidget#Navigation::item:hover { background: #203e59; }
QListWidget#Navigation::item:selected { background: #256451; color: white; font-weight: 600; }
QLabel#PageTitle { font-size: 27px; font-weight: 700; color: #142b43; }
QLabel#Muted, QLabel#Footer { color: #738399; font-size: 12px; }
QFrame#Metric { background: white; border: 1px solid #e2e9f1; border-radius: 13px; }
QLabel#MetricValue { font-size: 29px; font-weight: 700; color: #1d6654; }
QLabel#MetricTitle { color: #738399; font-size: 12px; }
QPushButton { background: white; border: 1px solid #dce4ed; border-radius: 8px; padding: 10px 14px; font-weight: 500; }
QPushButton:hover { border-color: #91abbd; background: #f0f6fa; }
QPushButton:pressed { background: #e2edf3; }
QPushButton[primary="true"] { color: white; background: #246c58; border-color: #246c58; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #1b5848; }
QPushButton:disabled { color: #a1acb8; background: #eef1f5; }
QLineEdit, QPlainTextEdit, QComboBox { background: white; color: #25364b; border: 1px solid #dce4ed; border-radius: 8px; padding: 9px; selection-background-color: #d6eee4; selection-color: #153d2d; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: #34846a; }
QComboBox::drop-down { border: none; width: 24px; }
QTableWidget { background: white; alternate-background-color: #f8fafc; border: 1px solid #e1e8f0; border-radius: 10px; gridline-color: #eff3f7; selection-background-color: #e1f1eb; selection-color: #174d3e; }
QTableWidget::item { padding: 9px; border: none; color: #25364b; }
QTableWidget::item:selected, QTableWidget::item:selected:!active { background: #d5eade; color: #153d2d; }
QComboBox QAbstractItemView { background: white; color: #25364b; selection-background-color: #d5eade; selection-color: #153d2d; }
QCalendarWidget QAbstractItemView { background: white; color: #25364b; selection-background-color: #246c58; selection-color: white; }
QCalendarWidget QWidget#qt_calendar_navigationbar { background: #e4ecf3; }
QCalendarWidget QToolButton { color: #25364b; background: transparent; padding: 5px; }
QHeaderView::section { background: #edf2f7; border: none; border-bottom: 1px solid #dce4ed; padding: 12px 8px; color: #66788e; font-weight: 600; }
QTabWidget::pane { border: none; background: transparent; }
QScrollBar:vertical { width: 9px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd6e1; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { color: #738399; background: #f2f5fa; }
'''

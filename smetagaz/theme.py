"""Consistent light/dark appearance, compact tables and accessible controls."""
from PyQt6.QtGui import QFont,QColor,QPalette
def apply(app,dark=False,family='Segoe UI',size=10):
    app.setStyle('Fusion');app.setFont(QFont(family,max(9,min(13,size))))
    bg,panel,text,muted,line,hover,alt=('#111827','#1b2638','#e5edf8','#9aaac0','#344155','#26364d','#202d40') if dark else ('#f3f6fb','#ffffff','#17263d','#65758b','#dce4ef','#edf3fc','#f7f9fc')
    palette=QPalette()
    for role,color in [(QPalette.ColorRole.Window,bg),(QPalette.ColorRole.WindowText,text),(QPalette.ColorRole.Base,panel),(QPalette.ColorRole.AlternateBase,alt),(QPalette.ColorRole.Text,text),(QPalette.ColorRole.Button,panel),(QPalette.ColorRole.ButtonText,text),(QPalette.ColorRole.Highlight,'#2563eb'),(QPalette.ColorRole.HighlightedText,'#ffffff'),(QPalette.ColorRole.ToolTipBase,panel),(QPalette.ColorRole.ToolTipText,text)]:palette.setColor(role,QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.Text,QColor(muted));app.setPalette(palette)
    app.setStyleSheet(f'''
    QWidget {{ color:{text}; }} QMainWindow,QDialog {{ background:{bg}; }}
    QToolTip {{ background:{panel};color:{text};border:1px solid {line};padding:6px; }}
    QFrame#sidebar {{background:#142238; border:0;}} QFrame#sidebar QLabel {{color:#b7c5dc;}}
    QLabel#brand {{font-size:18px;font-weight:700;color:#ffffff;}}
    QScrollArea#navigation {{background:transparent;border:0;}} QWidget#navContent {{background:#142238;}}
    QPushButton#navButton {{text-align:left;background:transparent;color:#b7c5dc;border:0;border-radius:7px;padding:8px 12px;min-height:20px;}}
    QPushButton#navButton:hover {{background:#20334f;color:white;}} QPushButton#navButton:checked {{background:#2563eb;color:white;font-weight:600;}}
    QLabel#pageTitle {{font-size:23px;font-weight:700;}} QLabel#pageSubtitle {{color:{muted};font-size:11px;}}
    QFrame#pageHeader {{background:{panel};border-bottom:1px solid {line};}}
    QPushButton {{background:{panel};border:1px solid {line};border-radius:6px;padding:6px 11px;min-height:20px;}}
    QPushButton:hover {{background:{hover};border-color:#a5b8d5;}} QPushButton:pressed {{background:#dbeafe;color:#17263d;}}
    QPushButton[type="primary"] {{background:#2563eb;border-color:#2563eb;color:white;font-weight:600;}}
    QPushButton[type="primary"]:hover {{background:#1d4ed8;}} QPushButton:disabled {{color:{muted};background:{alt};}}
    QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QDateEdit,QTimeEdit {{background:{panel};border:1px solid {line};border-radius:5px;padding:5px 7px;min-height:20px;selection-background-color:#2563eb;selection-color:white;}}
    QLineEdit:focus,QTextEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus,QDateEdit:focus {{border:1px solid #2563eb;}}
    QComboBox::drop-down,QDateEdit::drop-down {{border:0;width:23px;}}
    QComboBox QAbstractItemView {{background:{panel};selection-background-color:#2563eb;selection-color:white;}}
    QTableView {{qproperty-showGrid:false;qproperty-alternatingRowColors:true;}}
    QTableView,QTreeView,QListView {{background:{panel};alternate-background-color:{alt};border:1px solid {line};border-radius:7px;selection-background-color:#dbeafe;selection-color:#142238;outline:0;}}
    QTableView::item,QTreeView::item,QListView::item {{padding:5px;border-bottom:1px solid {alt};}}
    QTreeView::item:selected {{background:#dbeafe;color:#142238;}}
    QHeaderView::section {{background:{alt};color:{muted};font-weight:600;padding:8px;border:0;border-bottom:1px solid {line};}}
    QTabWidget::pane {{background:{panel};border:1px solid {line};border-radius:6px;top:-1px;}}
    QTabBar::tab {{background:{bg};color:{muted};border:0;padding:9px 14px;margin-right:3px;}}
    QTabBar::tab:selected {{background:{panel};color:#2563eb;border-bottom:2px solid #2563eb;font-weight:600;}}
    QGroupBox {{background:{panel};border:1px solid {line};border-radius:8px;margin-top:15px;padding:15px 10px 10px;}}
    QGroupBox::title {{subcontrol-origin:margin;left:12px;padding:0 5px;color:{muted};font-weight:600;}}
    QFrame#metricCard {{background:{panel};border:1px solid {line};border-radius:9px;padding:12px;}}
    QScrollArea {{border:0;background:transparent;}} QScrollBar:vertical {{background:{bg};width:9px;margin:0;}}
    QScrollBar::handle:vertical {{background:#8194ad;border-radius:4px;min-height:30px;}}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
    QScrollBar:horizontal {{background:{bg};height:9px;}} QScrollBar::handle:horizontal {{background:#8194ad;border-radius:4px;min-width:30px;}}
    QProgressBar {{border:0;background:{line};border-radius:5px;text-align:center;}} QProgressBar::chunk {{background:#2563eb;border-radius:5px;}}
    QMenu {{background:{panel};border:1px solid {line};padding:5px;}} QMenu::item {{padding:7px 22px;border-radius:4px;}} QMenu::item:selected {{background:{hover};}}
    ''')

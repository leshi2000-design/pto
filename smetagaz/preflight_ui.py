"""Окно сверки перед формированием документа."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem
from PyQt6.QtGui import QColor


def confirm(parent, title, issues):
    """True — формировать (замечаний нет или пользователь выбрал «Всё равно сформировать»)."""
    if not issues:
        return True
    d = QDialog(parent)
    d.setWindowTitle('Сверка перед формированием')
    d.resize(720, 420)
    layout = QVBoxLayout(d)
    errors = sum(1 for i in issues if i['level'] == 'error')
    head = QLabel(f'<b>{title}</b><br>Найдено замечаний: {len(issues)}' + (f' (важных: {errors})' if errors else '') + '. Эти поля попадут в документ пустыми или устаревшими.')
    head.setWordWrap(True)
    layout.addWidget(head)
    lst = QListWidget()
    lst.setWordWrap(True)
    for i in sorted(issues, key=lambda x: x['level'] != 'error'):
        item = QListWidgetItem(('⛔ ' if i['level'] == 'error' else '⚠ ') + i['text'])
        item.setForeground(QColor('#DC2626' if i['level'] == 'error' else '#B45309'))
        lst.addItem(item)
    layout.addWidget(lst, 1)
    bar = QHBoxLayout()
    bar.addStretch()
    back = QPushButton('Вернуться и исправить')
    back.setProperty('type', 'primary')
    back.setDefault(True)
    back.clicked.connect(d.reject)
    go = QPushButton('Всё равно сформировать')
    go.clicked.connect(d.accept)
    bar.addWidget(back)
    bar.addWidget(go)
    layout.addLayout(bar)
    return d.exec() == QDialog.DialogCode.Accepted

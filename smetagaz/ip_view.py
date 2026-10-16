"""Раздел «СМР (ИП)»: договоры и акты, сметы без договора, оплаты без договора, ведомость работ и оплат по месяцам, налог. Связан только с клиентами и сметами."""
from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                              QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import ip_domain as ip
from .counterparty_ui import ActsRegistry, ContractsRegistry, PersonDialog, TemplatesTab, populate_person_combo
from .database import db
from .date_widgets import DateEdit


def money(v):
    return ip.money(v)


def make_table(headers, stretch=None):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if stretch is not None:
        t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return t


def fill(table, rows, data=None, right=(), colors=None):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            item = QTableWidgetItem('' if v is None else str(v))
            if c == 0 and data is not None:
                item.setData(Qt.ItemDataRole.UserRole, data[r])
            if c in right:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if colors and colors.get((r, c)):
                item.setForeground(QColor(colors[(r, c)]))
            table.setItem(r, c, item)


def current_id(table):
    r = table.currentRow()
    item = table.item(r, 0) if r >= 0 else None
    return item.data(Qt.ItemDataRole.UserRole) if item else None


class NewEstimateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Новая смета ИП (без договора)')
        self.resize(480, 180)
        self.result = None
        f = QFormLayout(self)
        self.client = QComboBox()
        populate_person_combo(self.client)
        new = QPushButton('＋ Новый клиент…')
        new.clicked.connect(self.new_client)
        row = QHBoxLayout()
        row.addWidget(self.client, 1)
        row.addWidget(new)
        self.title = QLineEdit()
        self.title.setPlaceholderText('Например: ремонт кровли, ул. Лесная 5')
        self.manual = QLineEdit()
        self.manual.setPlaceholderText('или впишите клиента вручную (если выбран в списке — не нужно)')
        f.addRow('Клиент', row)
        f.addRow('Клиент вручную', self.manual)
        f.addRow('Название сметы', self.title)
        ok = QPushButton('Создать и открыть')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.accept_data)
        f.addRow(ok)

    def new_client(self):
        d = PersonDialog(self)
        if d.exec():
            populate_person_combo(self.client, d.person_id)

    def accept_data(self):
        name = self.manual.text().strip()
        client_id = None if name else self.client.currentData()      # впечатанное вручную имеет приоритет над списком
        if not client_id and not name:
            QMessageBox.warning(self, 'Смета', 'Выберите клиента или впишите его вручную')
            return
        self.result = (client_id, self.title.text().strip(), name)
        self.accept()


class EstimatesTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Сметы ИП: без договора и по договорам ИП. Смета без договора нужна, когда клиент просто заказал работу.'))
        bar = QHBoxLayout()
        for text, fn in (('Новая смета без договора', self.create), ('Добавить существующую…', self.attach), ('Открыть', self.open), ('Оплаты…', self.payments), ('Убрать из ИП', self.detach)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if text.startswith('Новая'):
                b.setProperty('type', 'primary')
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.table = make_table(['Смета', 'Клиент', 'Дата', 'Итого', 'Оплачено', 'Долг', 'Договор'], 0)
        self.table.doubleClicked.connect(lambda *_: self.open())
        layout.addWidget(self.table, 1)
        self.load_data()

    def load_data(self):
        rows = ip.estimates(db)
        fill(self.table, [(e['title'], e['client'], e['date'], money(e['total']), money(e['paid']), money(e['debt']), e['contract'] or '— без договора —') for e in rows],
             data=[e['id'] for e in rows], right=(3, 4, 5), colors={(r, 5): '#DC2626' for r, e in enumerate(rows) if e['debt'] > 0})

    def create(self):
        d = NewEstimateDialog(self)
        if d.exec() and d.result:
            eid = ip.add_estimate(db, *d.result)
            self.load_data()
            self.open_estimate(eid)

    def attach(self):
        from .workspace_view import choose_client
        d = QDialog(self)
        d.setWindowTitle('Добавить существующую смету в ИП')
        d.resize(620, 420)
        lay = QVBoxLayout(d)
        search = QLineEdit()
        search.setPlaceholderText('Название сметы или клиент…')
        lay.addWidget(search)
        table = make_table(['Смета', 'Клиент', 'Итого'], 0)
        lay.addWidget(table, 1)

        def load():
            q = f'%{search.text().casefold()}%'
            rows = db.fetchall("""SELECT id,title,client_name,total FROM estimates WHERE id NOT IN (SELECT estimate_id FROM ip_estimates)
                AND LOWER(coalesce(title,'')||' '||coalesce(client_name,'')) LIKE ? ORDER BY coalesce(date,'') DESC,id DESC LIMIT 300""", (q,))
            fill(table, [(r[1], r[2], money(r[3])) for r in rows], data=[r[0] for r in rows], right=(2,))
        search.textChanged.connect(load)
        load()
        ok = QPushButton('Добавить выбранную')
        ok.setProperty('type', 'primary')
        lay.addWidget(ok)

        def pick():
            eid = current_id(table)
            if not eid:
                return
            try:
                ip.attach_estimate(db, eid)
            except ValueError as e:
                QMessageBox.warning(d, 'Смета', str(e))
                return
            d.accept()
        ok.clicked.connect(pick)
        table.doubleClicked.connect(lambda *_: pick())
        if d.exec():
            self.load_data()

    def open_estimate(self, eid):
        from .estimate_editor import EstimateEditorDialog
        row = db.fetchone('SELECT title FROM estimates WHERE id=?', (eid,))
        if row:
            EstimateEditorDialog(eid, row[0] or '', self).exec()
            self.load_data()

    def open(self):
        eid = current_id(self.table)
        if eid:
            self.open_estimate(eid)

    def payments(self):
        eid = current_id(self.table)
        if eid:
            from .payments_view import PaymentsDialog
            PaymentsDialog('estimates', eid, self).exec()
            self.load_data()

    def detach(self):
        eid = current_id(self.table)
        if eid and QMessageBox.question(self, 'Убрать из ИП', 'Смета останется в «Реестре смет», но перестанет учитываться в разделе ИП (в ведомости и налоге). Продолжить?') == QMessageBox.StandardButton.Yes:
            ip.detach_estimate(db, eid)
            self.load_data()


class IncomeDialog(QDialog):
    def __init__(self, iid=None, parent=None):
        super().__init__(parent)
        self.iid = iid
        self.setWindowTitle('Оплата без договора')
        self.resize(500, 300)
        f = QFormLayout(self)
        self.client = QComboBox()
        populate_person_combo(self.client)
        new = QPushButton('＋ Новый клиент…')
        new.clicked.connect(self.new_client)
        row = QHBoxLayout()
        row.addWidget(self.client, 1)
        row.addWidget(new)
        self.date = DateEdit(QDate.currentDate())
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e9)
        self.amount.setDecimals(2)
        self.amount.setSuffix(' BYN')
        self.title = QLineEdit()
        self.title.setPlaceholderText('За что оплата')
        self.note = QLineEdit()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText('или впишите клиента вручную (если выбран в списке — не нужно)')
        f.addRow('Клиент', row)
        f.addRow('Клиент вручную', self.manual)
        f.addRow('Дата оплаты', self.date)
        f.addRow('Сумма', self.amount)
        f.addRow('За что', self.title)
        f.addRow('Примечание', self.note)
        ok = QPushButton('Сохранить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        f.addRow(ok)
        if iid:
            r = db.fetchone('SELECT client_id,income_date,amount,title,note,client_name FROM ip_income WHERE id=?', (iid,))
            populate_person_combo(self.client, r[0])
            if not r[0]:
                self.manual.setText(r[5] or '')
            self.date.setDate(QDate.fromString(r[1], 'yyyy-MM-dd'))
            self.amount.setValue(r[2])
            self.title.setText(r[3] or '')
            self.note.setText(r[4] or '')

    def new_client(self):
        d = PersonDialog(self)
        if d.exec():
            populate_person_combo(self.client, d.person_id)

    def save(self):
        try:
            name = self.manual.text().strip()
            ip.save_income(db, dict(client_id=None if name else self.client.currentData(), client_name=name, date=self.date.date().toString('yyyy-MM-dd'), amount=self.amount.value(), title=self.title.text(), note=self.note.text()), self.iid)
        except ValueError as e:
            QMessageBox.warning(self, 'Оплата не сохранена', str(e))
            return
        self.accept()


class IncomeTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Оплаты, когда клиент просто рассчитался за работу — без договора и без сметы. Оплаты по договорам и сметам ведутся в их карточках, здесь они тоже видны.'))
        bar = QHBoxLayout()
        self.year = QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(date.today().year)
        self.year.valueChanged.connect(self.load_data)
        bar.addWidget(QLabel('Год'))
        bar.addWidget(self.year)
        self.only_free = QCheckBox('Только без договора')
        self.only_free.setChecked(True)
        self.only_free.toggled.connect(self.load_data)
        bar.addWidget(self.only_free)
        for text, fn in (('Добавить оплату', self.add), ('Изменить', self.edit), ('Удалить', self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if text.startswith('Добавить'):
                b.setProperty('type', 'primary')
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.table = make_table(['Дата', 'Клиент', 'Вид', 'За что', 'Сумма'], 3)
        self.table.doubleClicked.connect(lambda *_: self.edit())
        layout.addWidget(self.table, 1)
        self.total = QLabel('')
        layout.addWidget(self.total)
        self.load_data()

    def load_data(self, *_):
        y = self.year.value()
        rows = [r for r in ip.incomes(db, date(y, 1, 1), date(y, 12, 31)) if not self.only_free.isChecked() or r['kind'] == 'Без договора']
        rows.sort(key=lambda r: r['date'], reverse=True)
        fill(self.table, [(r['date'], r['client'], r['kind'], r['label'], money(r['amount'])) for r in rows],
             data=[r['ref'][1] if r['kind'] == 'Без договора' else None for r in rows], right=(4,))
        self.total.setText(f'Итого за {y} год: {money(sum(r["amount"] for r in rows))} BYN · записей: {len(rows)}')

    def add(self):
        IncomeDialog(None, self).exec()
        self.load_data()

    def edit(self):
        iid = current_id(self.table)
        if iid:
            IncomeDialog(iid, self).exec()
            self.load_data()
        else:
            QMessageBox.information(self, 'Оплата', 'Оплаты по договорам и сметам изменяются в их карточках (кнопка «Оплаты»).')

    def delete(self):
        iid = current_id(self.table)
        if iid and QMessageBox.question(self, 'Удалить оплату', 'Удалить выбранную оплату?') == QMessageBox.StandardButton.Yes:
            ip.delete_income(db, iid)
            self.load_data()


class StatementTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.year = QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(date.today().year)
        self.month = QComboBox()
        for m in range(1, 13):
            self.month.addItem(ip.MONTHS[m].capitalize(), m)
        self.month.setCurrentIndex(date.today().month - 1)
        bar.addWidget(QLabel('Год'))
        bar.addWidget(self.year)
        bar.addWidget(QLabel('Месяц'))
        bar.addWidget(self.month)
        bar.addStretch()
        for text, fn in (('Выгрузить в Excel…', self.export), ('PDF', self.pdf), ('Печать', self.print_)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        layout.addLayout(bar)
        self.summary = make_table(['Месяц', 'Выполнено работ', 'Получено оплат', 'Не оплачено'], 0)
        self.summary.setMaximumHeight(300)
        self.summary.itemSelectionChanged.connect(self.pick_month)
        layout.addWidget(self.summary)
        layout.addWidget(QLabel('<b>Выполненные работы за месяц</b> (подписанные акты и сметы без договора)'))
        self.works = make_table(['Дата', 'Вид', 'Основание', 'Клиент', 'Сумма', 'Учтено'], 2)
        layout.addWidget(self.works, 1)
        layout.addWidget(QLabel('<b>Оплаты за месяц</b>'))
        self.payments = make_table(['Дата', 'Вид', 'Основание', 'Клиент', 'Сумма'], 2)
        layout.addWidget(self.payments, 1)
        self.totals = QLabel('')
        layout.addWidget(self.totals)
        self.year.valueChanged.connect(self.load_data)
        self.month.currentIndexChanged.connect(self.load_month)
        self.load_data()

    def load_data(self, *_):
        y = self.year.value()
        rows = ip.year_summary(db, y)
        fill(self.summary, [(ip.MONTHS[m].capitalize(), money(w), money(p), money(w - p)) for m, w, p in rows], data=[m for m, _w, _p in rows], right=(1, 2, 3))
        self.summary.insertRow(self.summary.rowCount())
        total_w, total_p = sum(r[1] for r in rows), sum(r[2] for r in rows)
        for c, v in enumerate(('Итого за год', money(total_w), money(total_p), money(total_w - total_p))):
            item = QTableWidgetItem(v)
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            if c:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.summary.setItem(self.summary.rowCount() - 1, c, item)
        self.load_month()

    def pick_month(self):
        m = current_id(self.summary)
        if m:
            self.month.setCurrentIndex(m - 1)

    def load_month(self, *_):
        st = ip.statement(db, self.year.value(), self.month.currentData())
        fill(self.works, [(w['date'], w['kind'], w['label'], w['client'], money(w['amount']), 'да' if w['counted'] else 'нет, акт не подписан') for w in st['works']], right=(4,),
             colors={(r, 5): '#B45309' for r, w in enumerate(st['works']) if not w['counted']})
        fill(self.payments, [(p['date'], p['kind'], p['label'], p['client'], money(p['amount'])) for p in st['payments']], right=(4,))
        self.totals.setText(f'<b>Выполнено: {money(st["works_total"])} · получено: {money(st["paid_total"])} · не оплачено за месяц: {money(st["balance"])} BYN</b>')

    def html(self):
        from .print_ui import card_html
        y, m = self.year.value(), self.month.currentData()
        st = ip.statement(db, y, m)
        sections = [('Выполненные работы', ('table', ['Дата', 'Вид', 'Основание', 'Клиент', 'Сумма', 'Учтено'],
                                           [(w['date'], w['kind'], w['label'], w['client'], money(w['amount']), 'да' if w['counted'] else 'нет') for w in st['works']] + [('', '', '', 'Итого', money(st['works_total']), '')])),
                    ('Оплаты', ('table', ['Дата', 'Вид', 'Основание', 'Клиент', 'Сумма'], [(p['date'], p['kind'], p['label'], p['client'], money(p['amount'])) for p in st['payments']] + [('', '', '', 'Итого', money(st['paid_total']))]))]
        return card_html(f'Ведомость работ и оплат ИП · {ip.MONTHS[m]} {y}', sections, f'не оплачено за месяц: {money(st["balance"])} BYN')

    def export(self):
        y, m = self.year.value(), self.month.currentData()
        path, _ = QFileDialog.getSaveFileName(self, 'Ведомость ИП', f'ведомость_ИП_{y}_{m:02}.xlsx', 'Excel (*.xlsx)')
        if path:
            ip.export_statement(db, y, m, path)
            from .platform_utils import open_local
            try:
                open_local(path)
            except OSError:
                pass

    def pdf(self):
        from . import print_ui
        print_ui.save_pdf(self, *self.html(), f'ведомость_ИП_{self.year.value()}_{self.month.currentData():02}')

    def print_(self):
        from . import print_ui
        print_ui.print_html(self, *self.html())


class ManualDialog(QDialog):
    """Ручные данные для налога: сумма выручки за квартал или месяц (когда нет договоров и актов) и уже уплаченный налог."""
    def __init__(self, year, mid=None, parent=None):
        super().__init__(parent)
        self.year, self.mid = year, mid
        self.setWindowTitle(f'Ручные данные для налога · {year} год')
        self.resize(480, 300)
        f = QFormLayout(self)
        self.kind = QComboBox()
        for key, text in ip.MANUAL_KINDS.items():
            self.kind.addItem(text, key)
        self.quarter = QComboBox()
        for q in (1, 2, 3, 4):
            self.quarter.addItem(f'{q}-й квартал', q)
        self.month = QComboBox()
        self.quarter.currentIndexChanged.connect(self.fill_months)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e9)
        self.amount.setDecimals(2)
        self.amount.setSuffix(' BYN')
        self.note = QLineEdit()
        self.note.setPlaceholderText('Например: итого за квартал по книге учёта')
        f.addRow('Что вводится', self.kind)
        f.addRow('Квартал', self.quarter)
        f.addRow('Период внутри квартала', self.month)
        f.addRow('Сумма', self.amount)
        f.addRow('Примечание', self.note)
        hint = QLabel('Сумма за весь квартал при расчёте делится поровну на три месяца (вычет на бедность применяется к каждому месяцу отдельно). Лучше вводить по месяцам, если суммы известны. Ручная выручка складывается с оплатами, внесёнными в программу.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #605E5C;')
        f.addRow(hint)
        ok = QPushButton('Сохранить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        f.addRow(ok)
        self.fill_months()
        if mid:
            r = db.fetchone('SELECT quarter,month,kind,amount,note FROM ip_manual WHERE id=?', (mid,))
            self.kind.setCurrentIndex(self.kind.findData(r[2]))
            self.quarter.setCurrentIndex(r[0] - 1)
            self.fill_months()
            self.month.setCurrentIndex(max(0, self.month.findData(r[1])))
            self.amount.setValue(r[3])
            self.note.setText(r[4] or '')

    def fill_months(self, *_):
        q = self.quarter.currentData()
        self.month.clear()
        self.month.addItem('Весь квартал', 0)
        for m in range(q * 3 - 2, q * 3 + 1):
            self.month.addItem(ip.MONTHS[m].capitalize(), m)

    def save(self):
        try:
            ip.save_manual(db, self.year, self.quarter.currentData(), self.month.currentData(), self.kind.currentData(), self.amount.value(), self.note.text(), self.mid)
        except ValueError as e:
            QMessageBox.warning(self, 'Данные не сохранены', str(e))
            return
        self.accept()


class TaxTab(QWidget):
    """Подоходный налог ИП: параметры года (меняются вручную в начале года) и автоматический расчёт за квартал."""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.year = QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(date.today().year)
        self.quarter = QComboBox()
        for q in (1, 2, 3, 4):
            self.quarter.addItem(f'{q}-й квартал', q)
        self.quarter.setCurrentIndex((date.today().month - 1) // 3)
        top.addWidget(QLabel('Год'))
        top.addWidget(self.year)
        top.addWidget(QLabel('Отчётный квартал'))
        top.addWidget(self.quarter)
        top.addStretch()
        refresh = QPushButton('Пересчитать')
        refresh.clicked.connect(self.load_data)
        top.addWidget(refresh)
        layout.addLayout(top)
        self.result = QLabel('')
        self.result.setTextFormat(Qt.TextFormat.RichText)
        self.result.setStyleSheet('padding: 10px; border: 1px solid #9AA5A3; border-radius: 8px; font-size: 12pt;')
        layout.addWidget(self.result)
        self.table = make_table(['Месяц', 'Выручка', 'Затраты (20 %)', 'Вычет на бедность', 'Вычет на детей', 'Вычет на иждивенцев', 'Налоговая база', 'Налог'], 0)
        self.table.setMaximumHeight(230)
        layout.addWidget(self.table)
        box = QGroupBox('Параметры года (стандартные значения; в начале года проверьте и при необходимости измените)')
        g = QGridLayout(box)
        self.fields = {}
        specs = [('expense_rate', 'Нормативные затраты, % от выручки', 0, 100, 2), ('tax_rate', 'Ставка подоходного налога, %', 0, 100, 2),
                 ('poverty_threshold', 'Порог дохода за месяц для вычета на бедность, BYN', 0, 1e7, 2), ('poverty_deduction', 'Вычет на бедность, BYN', 0, 1e7, 2),
                 ('child_deduction', 'Вычет на 1 ребёнка, BYN в месяц', 0, 1e7, 2), ('dependent_deduction', 'Вычет на 1 иждивенца, BYN в месяц', 0, 1e7, 2),
                 ('children', 'Количество детей', 0, 50, 0), ('dependents', 'Количество иждивенцев', 0, 50, 0)]
        for i, (key, label, lo, hi, dec) in enumerate(specs):
            w = QDoubleSpinBox() if dec else QSpinBox()
            w.setRange(lo, hi)
            if dec:
                w.setDecimals(dec)
            self.fields[key] = w
            g.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            g.addWidget(w, i // 2, (i % 2) * 2 + 1)
        self.monthly = QCheckBox('Вычеты применяются помесячно (налоговая база месяца не бывает отрицательной)')
        g.addWidget(self.monthly, 4, 0, 1, 4)
        save = QPushButton('Сохранить параметры года')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save_params)
        g.addWidget(save, 5, 0, 1, 4)
        layout.addWidget(box)
        layout.addWidget(QLabel('<b>Налог по кварталам года</b> (оплаты из программы + ручные данные)'))
        self.quarters = make_table(['Квартал', 'Выручка', 'в т.ч. вручную', 'Налоговая база', 'Налог', 'Уплачено', 'Осталось уплатить'], 0)
        self.quarters.setMaximumHeight(190)
        layout.addWidget(self.quarters)
        manual_box = QGroupBox('Ручные данные (суммы за кварталы без договоров и актов, уплаченный налог)')
        ml = QVBoxLayout(manual_box)
        bar = QHBoxLayout()
        for text, fn in (('Добавить', self.add_manual), ('Изменить', self.edit_manual), ('Удалить', self.delete_manual)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        ml.addLayout(bar)
        self.manual_table = make_table(['Квартал', 'Период', 'Что', 'Сумма', 'Примечание'], 4)
        self.manual_table.setMaximumHeight(170)
        self.manual_table.doubleClicked.connect(lambda *_: self.edit_manual())
        ml.addWidget(self.manual_table)
        layout.addWidget(manual_box)
        layout.addStretch()
        self.year.valueChanged.connect(self.reload_all)
        self.quarter.currentIndexChanged.connect(self.load_data)
        self.reload_all()

    def reload_all(self, *_):
        p = ip.params(db, self.year.value())
        for key, w in self.fields.items():
            w.blockSignals(True)
            w.setValue(p[key])
            w.blockSignals(False)
        self.monthly.setChecked(bool(p['monthly']))
        self.load_data()

    def add_manual(self):
        if ManualDialog(self.year.value(), None, self).exec():
            self.load_data()

    def edit_manual(self):
        mid = current_id(self.manual_table)
        if mid and ManualDialog(self.year.value(), mid, self).exec():
            self.load_data()

    def delete_manual(self):
        mid = current_id(self.manual_table)
        if mid and QMessageBox.question(self, 'Удалить', 'Удалить выбранную запись?') == QMessageBox.StandardButton.Yes:
            ip.delete_manual(db, mid)
            self.load_data()

    def save_params(self):
        try:
            ip.save_params(db, self.year.value(), {**{k: w.value() for k, w in self.fields.items()}, 'monthly': int(self.monthly.isChecked())})
        except ValueError as e:
            QMessageBox.warning(self, 'Параметры', str(e))
            return
        self.load_data()

    def load_data(self, *_):
        y, q = self.year.value(), self.quarter.currentData()
        r = ip.quarter_report(db, y, q)
        fill(self.table, [(m['name'].capitalize(), money(m['revenue']), money(m['expenses']), money(m['poverty']), money(m['children']), money(m['dependents']), money(m['base']), money(m['tax']))
                          for m in r['months']] + [('Итого за квартал', money(r['revenue']), '', '', '', '', money(r['base']), money(r['tax']))], right=(1, 2, 3, 4, 5, 6, 7))
        last = self.table.rowCount() - 1
        for c in range(8):
            if self.table.item(last, c):
                f = self.table.item(last, c).font()
                f.setBold(True)
                self.table.item(last, c).setFont(f)
        state = 'квартал завершён' if r['complete'] else f'по состоянию на {date.today():%d.%m.%Y}, квартал ещё идёт'
        paid_text = f' · уплачено {money(r["paid"])} · осталось уплатить {money(r["to_pay"])}' if r['paid'] else ''
        self.result.setText(f'<b>К уплате за {q}-й квартал {y} года: {money(r["tax"])} BYN</b><br><span style="font-size:10pt">Выручка {money(r["revenue"])} · налоговая база {money(r["base"])}{paid_text} · {state}</span>')
        quarters = ip.year_report(db, y)
        total = lambda key: sum(x[key] for x in quarters)
        fill(self.quarters, [(f'{x["quarter"]}-й квартал', money(x['revenue']), money(x['manual']), money(x['base']), money(x['tax']), money(x['paid']), money(x['to_pay'])) for x in quarters] +
             [('Итого за год', money(total('revenue')), money(total('manual')), money(total('base')), money(total('tax')), money(total('paid')), money(total('to_pay')))], right=(1, 2, 3, 4, 5, 6))
        last_row = self.quarters.rowCount() - 1
        for c in range(7):
            if self.quarters.item(last_row, c):
                font = self.quarters.item(last_row, c).font()
                font.setBold(True)
                self.quarters.item(last_row, c).setFont(font)
        rows = ip.manual_list(db, y)
        fill(self.manual_table, [(f'{q_}-й', ip.MONTHS[m].capitalize() if m else 'весь квартал', ip.MANUAL_KINDS[k], money(a), n) for _i, q_, m, k, a, n in rows], data=[r_[0] for r_ in rows], right=(3,))


class IpView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.pages = [(ContractsRegistry('ip'), 'Договоры'), (ActsRegistry('ip'), 'Акты'), (EstimatesTab(), 'Сметы'), (IncomeTab(), 'Оплаты'), (StatementTab(), 'Ведомость по месяцам'),
                      (TaxTab(), 'Налог'), (TemplatesTab('ip'), 'Шаблоны и теги')]
        for widget, title in self.pages:
            self.tabs.addTab(widget, title)
        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda *_: self.load_data())

    def load_data(self):
        w = self.tabs.currentWidget()
        if hasattr(w, 'load_data'):
            w.load_data()
        elif hasattr(w, 'reload_all'):
            w.reload_all()

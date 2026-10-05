from PyQt6.QtWidgets import QWidget,QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QListWidget,QListWidgetItem,QPushButton,QLineEdit,QTableWidget,QTableWidgetItem,QMessageBox,QLabel,QColorDialog,QTabWidget,QToolButton,QCheckBox,QFrame
from PyQt6.QtCore import Qt,QSize
from PyQt6.QtGui import QColor,QPixmap,QIcon
from .database import db
from .pagination import RegistryPager
from .agenda_domain import PALETTE,due_label,plural

DEFAULT_TAG_COLOR='#3B82F6'

def swatch(color):
    pix=QPixmap(14,14);pix.fill(QColor(color or DEFAULT_TAG_COLOR));return QIcon(pix)

def migrate(db):
    if 'status_name' not in [r[1] for r in db.fetchall('PRAGMA table_info(kanban_tasks)')]:db.execute("ALTER TABLE kanban_tasks ADD COLUMN status_name TEXT DEFAULT ''")
    if 'tags' not in [r[1] for r in db.fetchall('PRAGMA table_info(kanban_tasks)')]:db.execute("ALTER TABLE kanban_tasks ADD COLUMN tags TEXT DEFAULT ''")
    db.execute('CREATE TABLE IF NOT EXISTS task_statuses(id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL UNIQUE)');db.execute('CREATE TABLE IF NOT EXISTS task_tags(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE)');db.execute('CREATE TABLE IF NOT EXISTS task_tag_links(task_id INTEGER REFERENCES kanban_tasks(id) ON DELETE CASCADE,tag_id INTEGER REFERENCES task_tags(id) ON DELETE RESTRICT,PRIMARY KEY(task_id,tag_id))')
    if 'color' not in [r[1] for r in db.fetchall('PRAGMA table_info(task_tags)')]:db.execute(f"ALTER TABLE task_tags ADD COLUMN color TEXT DEFAULT '{DEFAULT_TAG_COLOR}'")
    for code,name in [('todo','К выполнению'),('in_progress','В работе'),('done','Готово')]:db.execute('INSERT OR IGNORE INTO task_statuses(code,name) VALUES(?,?)',(code,name))
    for (code,) in db.fetchall('SELECT DISTINCT status FROM kanban_tasks WHERE status IS NOT NULL'):db.execute('INSERT OR IGNORE INTO task_statuses(code,name) VALUES(?,?)',(code,code))
    db.execute("UPDATE kanban_tasks SET status_name=coalesce((SELECT name FROM task_statuses WHERE code=kanban_tasks.status),status)")
    for action in ('INSERT','UPDATE OF status'):
        suffix='insert' if action=='INSERT' else 'update'
        db.execute(f"CREATE TRIGGER IF NOT EXISTS task_status_name_{suffix} AFTER {action} ON kanban_tasks BEGIN UPDATE kanban_tasks SET status_name=coalesce((SELECT name FROM task_statuses WHERE code=new.status),new.status) WHERE id=new.id; END")
def refresh_tags():
    db.execute("UPDATE kanban_tasks SET status_name=coalesce((SELECT name FROM task_statuses WHERE code=kanban_tasks.status),status)")
    db.execute("UPDATE kanban_tasks SET tags=coalesce((SELECT group_concat(name,', ') FROM (SELECT t.name FROM task_tag_links l JOIN task_tags t ON t.id=l.tag_id WHERE l.task_id=kanban_tasks.id ORDER BY t.name)),'')")
class TaskFields(QWidget):
    def __init__(self,task_id=None):
        super().__init__();l=QVBoxLayout(self);self.status=QComboBox()
        for code,name in db.fetchall('SELECT code,name FROM task_statuses ORDER BY sort_order,id'):self.status.addItem(name,code)
        l.addWidget(QLabel('Статус'));l.addWidget(self.status);self.tags=QListWidget();self.tags.setMaximumHeight(100);l.addWidget(QLabel('Теги — можно выбрать несколько'));l.addWidget(self.tags)
        selected={r[0] for r in db.fetchall('SELECT tag_id FROM task_tag_links WHERE task_id=?',(task_id,))}
        for tid,name,color in db.fetchall('SELECT id,name,color FROM task_tags ORDER BY name'):item=QListWidgetItem(swatch(color),name);item.setData(Qt.ItemDataRole.UserRole,tid);item.setCheckState(Qt.CheckState.Checked if tid in selected else Qt.CheckState.Unchecked);self.tags.addItem(item)
        row=db.fetchone('SELECT status FROM kanban_tasks WHERE id=?',(task_id,))
        if row:self.status.setCurrentIndex(max(0,self.status.findData(row[0])))
    def save(self,rid):
        db.execute('UPDATE kanban_tasks SET status=? WHERE id=?',(self.status.currentData(),rid));db.execute('DELETE FROM task_tag_links WHERE task_id=?',(rid,))
        for i in range(self.tags.count()):
            item=self.tags.item(i)
            if item.checkState()==Qt.CheckState.Checked:db.execute('INSERT INTO task_tag_links(task_id,tag_id) VALUES(?,?)',(rid,item.data(Qt.ItemDataRole.UserRole)))
        refresh_tags()
def ink_for(color):
    """Чёрный или белый текст, читаемый на заданном фоне."""
    c=QColor(color or DEFAULT_TAG_COLOR)
    return '#0f172a' if (c.red()*299+c.green()*587+c.blue()*114)/1000>170 else '#ffffff'
def chip_html(name,color,size=10):
    from html import escape
    bg=color or DEFAULT_TAG_COLOR
    return f'<span style="background-color:{bg};color:{ink_for(bg)};font-size:{size}px;">&nbsp;{escape(name)}&nbsp;</span>'
def status_rows():
    """(code, name, color, is_done) в порядке колонок доски."""
    return db.fetchall('SELECT code,name,coalesce(color,?),coalesce(is_done,0) FROM task_statuses ORDER BY sort_order,id',(DEFAULT_TAG_COLOR,))

class CatalogPage(QWidget):
    """Одна вкладка справочника: список слева, карточка редактирования справа."""
    def __init__(self,kind,parent=None):
        super().__init__(parent);self.kind=kind;self.is_tag=kind=='tags';self.table='task_tags' if self.is_tag else 'task_statuses';self.current_id=None;self.color=DEFAULT_TAG_COLOR
        root=QHBoxLayout(self);left=QVBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Поиск по названию');left.addWidget(self.search)
        self.list=QListWidget();self.list.setIconSize(QSize(16,16));self.list.setStyleSheet('QListWidget::item { padding: 7px 8px; border-radius: 6px; margin: 1px 2px; } QListWidget::item:hover { background: rgba(37,99,235,0.12); } QListWidget::item:selected, QListWidget::item:selected:active, QListWidget::item:selected:!active { background: #2563eb; color: #ffffff; font-weight: 600; }');left.addWidget(self.list,1);bar=QHBoxLayout()
        self.btn_new=QPushButton('＋ Новый тег' if self.is_tag else '＋ Новый статус');self.btn_new.setProperty('type','primary');bar.addWidget(self.btn_new)
        if not self.is_tag:
            self.btn_up=QPushButton('▲');self.btn_down=QPushButton('▼')
            for b,d in ((self.btn_up,-1),(self.btn_down,1)):b.setFixedWidth(36);b.setToolTip('Порядок колонок на доске');b.clicked.connect(lambda _,d=d:self.move(d));bar.addWidget(b)
        bar.addStretch();left.addLayout(bar);root.addLayout(left,5)
        self.form=QFrame();self.form.setObjectName('metricCard');form=QVBoxLayout(self.form);self.heading=QLabel();self.heading.setStyleSheet('font-weight:700;font-size:14px;');form.addWidget(self.heading)
        form.addWidget(QLabel('Название'));self.name=QLineEdit();form.addWidget(self.name)
        form.addWidget(QLabel('Цвет'));swatches=QHBoxLayout();swatches.setSpacing(5);self.swatch_buttons=[]
        for color in PALETTE:
            b=QToolButton();b.setFixedSize(26,26);b.setCursor(Qt.CursorShape.PointingHandCursor);b.clicked.connect(lambda _,c=color:self.set_color(c));self.swatch_buttons.append((color,b));swatches.addWidget(b)
        other=QToolButton();other.setText('…');other.setFixedSize(26,26);other.setToolTip('Другой цвет');other.clicked.connect(self.pick_color);swatches.addWidget(other);swatches.addStretch();form.addLayout(swatches)
        self.preview=QLabel();self.preview.setTextFormat(Qt.TextFormat.RichText);form.addWidget(QLabel('Так это выглядит на карточке:'));form.addWidget(self.preview)
        if self.is_tag:
            form.addWidget(QLabel('Пояснение (необязательно)'));self.note=QLineEdit();form.addWidget(self.note)
        else:
            self.done=QCheckBox('Завершающий статус');self.done.setToolTip('Задачи в таком статусе не считаются просроченными');form.addWidget(self.done)
            hint=QLabel('Задачи в завершающем статусе не получают пометку «Просрочено».');hint.setWordWrap(True);hint.setStyleSheet('color:#65758b;font-size:11px;');form.addWidget(hint)
        self.usage=QLabel();self.usage.setStyleSheet('color:#65758b;');form.addWidget(self.usage);form.addStretch()
        row=QHBoxLayout();self.btn_delete=QPushButton('Удалить');self.btn_delete.setProperty('type','danger');self.btn_save=QPushButton('Сохранить');self.btn_save.setProperty('type','primary');row.addWidget(self.btn_delete);row.addStretch();row.addWidget(self.btn_save);form.addLayout(row);root.addWidget(self.form,4)
        self.search.textChanged.connect(self.load);self.list.currentItemChanged.connect(lambda cur,_:self.select(cur));self.btn_new.clicked.connect(self.start_new);self.btn_save.clicked.connect(self.save);self.btn_delete.clicked.connect(self.remove);self.name.textChanged.connect(self.update_preview);self.name.returnPressed.connect(self.save)
        self.load();self.start_new() if not self.list.count() else self.list.setCurrentRow(0)
    # --- список ---
    def usage_count(self,rid):
        if self.is_tag:return db.fetchone('SELECT count(*) FROM task_tag_links WHERE tag_id=?',(rid,))[0]
        return db.fetchone('SELECT count(*) FROM kanban_tasks WHERE status=(SELECT code FROM task_statuses WHERE id=?)',(rid,))[0]
    def load(self,*_,select=None):
        wanted=select or self.current_id;self.list.blockSignals(True);self.list.clear();needle='%'+self.search.text().strip().casefold()+'%'
        sql='SELECT id,name,coalesce(color,?) FROM task_tags WHERE LOWER(name) LIKE ? ORDER BY name' if self.is_tag else 'SELECT id,name,coalesce(color,?) FROM task_statuses WHERE LOWER(name) LIKE ? ORDER BY sort_order,id'
        for rid,name,color in db.fetchall(sql,(DEFAULT_TAG_COLOR,needle)):
            count=self.usage_count(rid);item=QListWidgetItem(swatch(color),f'{name}   ·   {count} {plural(count,("задача","задачи","задач"))}');item.setData(Qt.ItemDataRole.UserRole,rid);self.list.addItem(item)
            if rid==wanted:self.list.setCurrentItem(item)
        self.list.blockSignals(False)
    # --- форма ---
    def set_color(self,color):
        self.color=QColor(color).name();self.update_preview()
    def pick_color(self):
        picked=QColorDialog.getColor(QColor(self.color),self,'Цвет')
        if picked.isValid():self.set_color(picked.name())
    def update_preview(self,*_):
        for color,b in self.swatch_buttons:
            selected=color.lower()==self.color.lower();b.setStyleSheet(f'QToolButton{{background:{color};border-radius:13px;border:{"3px solid #0f172a" if selected else "1px solid #94a3b8"};}}')
        self.preview.setText(chip_html(self.name.text().strip() or ('Тег' if self.is_tag else 'Статус'),self.color,13))
    def start_new(self):
        self.current_id=None;self.list.blockSignals(True);self.list.clearSelection();self.list.setCurrentItem(None);self.list.blockSignals(False);self.heading.setText('Новый тег' if self.is_tag else 'Новый статус')
        self.name.clear();self.color=PALETTE[self.list.count()%len(PALETTE)]
        if self.is_tag:self.note.clear()
        else:self.done.setChecked(False)
        self.usage.setText('');self.btn_delete.setEnabled(False);self.update_preview();self.name.setFocus()
    def select(self,item):
        if not item:return
        rid=item.data(Qt.ItemDataRole.UserRole);self.current_id=rid;self.btn_delete.setEnabled(True)
        if self.is_tag:name,color,note=db.fetchone('SELECT name,coalesce(color,?),coalesce(description,\'\') FROM task_tags WHERE id=?',(DEFAULT_TAG_COLOR,rid));self.note.setText(note)
        else:
            name,color,done=db.fetchone('SELECT name,coalesce(color,?),coalesce(is_done,0) FROM task_statuses WHERE id=?',(DEFAULT_TAG_COLOR,rid));self.done.setChecked(bool(done))
        self.heading.setText(('Тег' if self.is_tag else 'Статус')+f' «{name}»');self.name.setText(name);self.color=color;self.usage.setText(f'Используется в задачах: {self.usage_count(rid)}');self.update_preview()
    def save(self):
        name=self.name.text().strip()
        if not name:QMessageBox.warning(self,'Справочник','Введите название');return
        try:
            with db.transaction():
                if self.is_tag:
                    if self.current_id:db.execute('UPDATE task_tags SET name=?,color=?,description=? WHERE id=?',(name,self.color,self.note.text().strip(),self.current_id))
                    else:self.current_id=db.execute('INSERT INTO task_tags(name,color,description) VALUES(?,?,?)',(name,self.color,self.note.text().strip())).lastrowid
                elif self.current_id:db.execute('UPDATE task_statuses SET name=?,color=?,is_done=? WHERE id=?',(name,self.color,int(self.done.isChecked()),self.current_id))
                else:
                    import uuid
                    order=(db.fetchone('SELECT max(sort_order) FROM task_statuses')[0] or 0)+1;self.current_id=db.execute('INSERT INTO task_statuses(code,name,color,is_done,sort_order) VALUES(?,?,?,?,?)',(uuid.uuid4().hex,name,self.color,int(self.done.isChecked()),order)).lastrowid
                refresh_tags()
        except Exception as e:
            QMessageBox.warning(self,'Справочник','Такое название уже есть' if 'UNIQUE' in str(e) else str(e));return
        self.load(select=self.current_id);self.select(self.list.currentItem())
    def move(self,direction):
        rid=self.current_id
        if not rid:return
        rows=[r[0] for r in db.fetchall('SELECT id FROM task_statuses ORDER BY sort_order,id')];i=rows.index(rid);j=i+direction
        if not 0<=j<len(rows):return
        rows[i],rows[j]=rows[j],rows[i]
        with db.transaction():
            for order,r in enumerate(rows,1):db.execute('UPDATE task_statuses SET sort_order=? WHERE id=?',(order,r))
        self.load(select=rid)
    def remove(self):
        rid=self.current_id
        if not rid:return
        if self.usage_count(rid):QMessageBox.warning(self,'Используется','Сначала уберите этот тег / статус из задач');return
        if not self.is_tag and db.fetchone('SELECT code FROM task_statuses WHERE id=?',(rid,))[0] in ('todo','in_progress','done'):QMessageBox.warning(self,'Базовый статус','Базовый статус можно переименовать и перекрасить, но не удалить');return
        if QMessageBox.question(self,'Удаление','Удалить выбранную запись справочника?')==QMessageBox.StandardButton.Yes:
            db.execute(f'DELETE FROM {self.table} WHERE id=?',(rid,));self.current_id=None;self.load();self.start_new() if not self.list.count() else self.list.setCurrentRow(0)
class CatalogDialog(QDialog):
    """Справочник тегов и статусов задач."""
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('Теги и статусы задач');self.resize(820,520);l=QVBoxLayout(self)
        intro=QLabel('Статусы — колонки доски задач, теги — цветные метки на карточках. Выберите запись слева, измените название и цвет, нажмите «Сохранить».');intro.setWordWrap(True);intro.setStyleSheet('color:#65758b;');l.addWidget(intro)
        self.tabs=QTabWidget();self.tags=CatalogPage('tags');self.statuses=CatalogPage('statuses');self.tabs.addTab(self.statuses,'Статусы (колонки доски)');self.tabs.addTab(self.tags,'Теги');l.addWidget(self.tabs,1)
        close=QPushButton('Закрыть');close.clicked.connect(self.accept);row=QHBoxLayout();row.addStretch();row.addWidget(close);l.addLayout(row)
class TasksTable(QWidget):
    def __init__(self):
        super().__init__();l=QVBoxLayout(self);self.pager=RegistryPager(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Задача, описание, статус или тег');bar.addWidget(self.search,1);self.status=QComboBox();self.tag=QComboBox();bar.addWidget(self.status);bar.addWidget(self.tag);self.archive=QComboBox();self.archive.addItems(['Активные','Архив','Все']);bar.addWidget(self.archive);l.addLayout(bar);bar=QHBoxLayout()
        for title,fn in [('Новая задача',lambda:self.edit(False)),('Изменить',lambda:self.edit(True)),('Теги и статусы',self.catalog)]:b=QPushButton(title);b.clicked.connect(fn);bar.addWidget(b)
        bar.addStretch();l.addLayout(bar);self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['Задача','Статус','Теги','Срок','Срочность','Создана']);self.table.setColumnWidth(0,320);self.table.horizontalHeader().setStretchLastSection(True);l.addWidget(self.table,1);self.table.cellDoubleClicked.connect(lambda *_:self.edit(True));self.reload_catalog()
        for w in (self.status,self.tag,self.archive):w.currentIndexChanged.connect(self.load_data)
        self.search.textChanged.connect(self.load_data);self.load_data()
    def reload_catalog(self):
        for combo,table in [(self.status,'task_statuses'),(self.tag,'task_tags')]:
            selected=combo.currentData();combo.blockSignals(True);combo.clear();combo.addItem('Все статусы' if table=='task_statuses' else 'Все теги',None)
            for rid,name in db.fetchall(f'SELECT {"code" if table=="task_statuses" else "id"},name FROM {table} ORDER BY name'):combo.addItem(name,rid)
            combo.setCurrentIndex(max(0,combo.findData(selected)));combo.blockSignals(False)
    def catalog(self):CatalogDialog(self).exec();self.reload_catalog();self.load_data()
    def edit(self,existing):
        r=self.table.currentRow()
        if existing and r<0:return
        from .tasks_view import TaskEditDialog
        TaskEditDialog(self.table.item(r,0).data(Qt.ItemDataRole.UserRole) if existing else None,self).exec();self.load_data()
    def load_data(self,*_):
        q='%'+self.search.text().casefold()+'%';sql="SELECT k.id,k.title,coalesce(s.name,k.status) status_name,k.tags,k.due_date,k.urgency,k.created_at,coalesce(s.is_done,0) is_done FROM kanban_tasks k LEFT JOIN task_statuses s ON s.code=k.status WHERE LOWER(k.title||' '||coalesce(k.description,'')||' '||coalesce(s.name,k.status)||' '||coalesce(k.tags,'')) LIKE ?";params=[q]
        if self.status.currentData():sql+=' AND k.status=?';params.append(self.status.currentData())
        if self.tag.currentData():sql+=' AND EXISTS(SELECT 1 FROM task_tag_links l WHERE l.task_id=k.id AND l.tag_id=?)';params.append(self.tag.currentData())
        if self.archive.currentIndex()<2:sql+=' AND k.is_archived=?';params.append(self.archive.currentIndex())
        rows=self.pager.fetch(sql+' ORDER BY k.id DESC',params);self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            row=list(row);row[4]=due_label(row[4],done=bool(row[7])) or '';overdue=row[4].startswith('Просрочено')
            for c,value in enumerate(row[1:7]):
                item=QTableWidgetItem(str(value or ''))
                if overdue and c==3:item.setForeground(QColor('#DC2626'))
                item.setData(Qt.ItemDataRole.UserRole,row[0]);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(r,c,item)
    def load_boards(self):self.load_data()

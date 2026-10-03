from PyQt6.QtWidgets import QWidget,QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QListWidget,QListWidgetItem,QPushButton,QLineEdit,QTableWidget,QTableWidgetItem,QMessageBox,QInputDialog,QLabel,QColorDialog
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor,QPixmap,QIcon
from .database import db
from .pagination import RegistryPager

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
        for code,name in db.fetchall('SELECT code,name FROM task_statuses ORDER BY id'):self.status.addItem(name,code)
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
class CatalogDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('Справочники задач');self.resize(600,470);l=QVBoxLayout(self);self.kind=QComboBox();self.kind.addItem('Теги','task_tags');self.kind.addItem('Статусы','task_statuses');l.addWidget(self.kind);self.search=QLineEdit();self.search.setPlaceholderText('Поиск');l.addWidget(self.search);self.list=QListWidget();l.addWidget(self.list,1);bar=QHBoxLayout()
        for title,fn in [('Добавить',lambda:self.edit(False)),('Переименовать',lambda:self.edit(True)),('Удалить',self.remove)]:b=QPushButton(title);b.clicked.connect(fn);bar.addWidget(b)
        l.addLayout(bar);self.kind.currentIndexChanged.connect(self.load);self.search.textChanged.connect(self.load);self.load()
    def load(self,*_):
        self.list.clear()
        table=self.kind.currentData()
        if table=='task_tags':
            for rid,name,color in db.fetchall('SELECT id,name,color FROM task_tags WHERE LOWER(name) LIKE ? ORDER BY name',('%'+self.search.text().casefold()+'%',)):
                item=QListWidgetItem(swatch(color),name);item.setData(Qt.ItemDataRole.UserRole,rid);item.setData(Qt.ItemDataRole.UserRole+1,color);self.list.addItem(item)
        else:
            for rid,name in db.fetchall(f'SELECT id,name FROM {table} WHERE LOWER(name) LIKE ? ORDER BY name',('%'+self.search.text().casefold()+'%',)):item=QListWidgetItem(name);item.setData(Qt.ItemDataRole.UserRole,rid);self.list.addItem(item)
    def edit(self,existing):
        item=self.list.currentItem()
        if existing and not item:return
        name,ok=QInputDialog.getText(self,'Название','Название',text=item.text() if existing else '')
        if not ok or not name.strip():return
        table=self.kind.currentData()
        color=None
        if table=='task_tags':
            current=QColor(item.data(Qt.ItemDataRole.UserRole+1)) if existing else QColor(DEFAULT_TAG_COLOR)
            picked=QColorDialog.getColor(current,self,'Цвет тега')
            if not picked.isValid():return
            color=picked.name()
        try:
            with db.transaction():
                if existing:
                    if table=='task_tags':db.execute('UPDATE task_tags SET name=?,color=? WHERE id=?',(name.strip(),color,item.data(Qt.ItemDataRole.UserRole)))
                    else:db.execute(f'UPDATE {table} SET name=? WHERE id=?',(name.strip(),item.data(Qt.ItemDataRole.UserRole)))
                elif table=='task_tags':db.execute('INSERT INTO task_tags(name,color) VALUES(?,?)',(name.strip(),color))
                else:
                    import uuid
                    db.execute('INSERT INTO task_statuses(code,name) VALUES(?,?)',(uuid.uuid4().hex,name.strip()))
                refresh_tags()
            self.load()
        except Exception as e:QMessageBox.warning(self,'Справочник',str(e))
    def remove(self):
        item=self.list.currentItem()
        if not item:return
        table=self.kind.currentData();rid=item.data(Qt.ItemDataRole.UserRole)
        used=db.fetchone('SELECT count(*) FROM task_tag_links WHERE tag_id=?',(rid,))[0] if table=='task_tags' else db.fetchone('SELECT count(*) FROM kanban_tasks WHERE status=(SELECT code FROM task_statuses WHERE id=?)',(rid,))[0]
        if used:QMessageBox.warning(self,'Используется','Сначала уберите этот тег / статус из задач');return
        if table=='task_statuses' and db.fetchone('SELECT code FROM task_statuses WHERE id=?',(rid,))[0] in ('todo','in_progress','done'):QMessageBox.warning(self,'Базовый статус','Базовый статус можно переименовать');return
        if QMessageBox.question(self,'Удаление','Удалить выбранную запись справочника?')==QMessageBox.StandardButton.Yes:db.execute(f'DELETE FROM {table} WHERE id=?',(rid,));self.load()
class TasksTable(QWidget):
    def __init__(self):
        super().__init__();l=QVBoxLayout(self);self.pager=RegistryPager(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Задача, описание, статус или тег');bar.addWidget(self.search,1);self.status=QComboBox();self.tag=QComboBox();bar.addWidget(self.status);bar.addWidget(self.tag);self.archive=QComboBox();self.archive.addItems(['Активные','Архив','Все']);bar.addWidget(self.archive);l.addLayout(bar);bar=QHBoxLayout()
        for title,fn in [('Новая задача',lambda:self.edit(False)),('Изменить',lambda:self.edit(True)),('Теги и статусы',self.catalog)]:b=QPushButton(title);b.clicked.connect(fn);bar.addWidget(b)
        bar.addStretch();l.addLayout(bar);self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['Задача','Статус','Теги','Срочность','Создана']);self.table.setColumnWidth(0,320);self.table.horizontalHeader().setStretchLastSection(True);l.addWidget(self.table,1);self.table.cellDoubleClicked.connect(lambda *_:self.edit(True));self.reload_catalog()
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
        q='%'+self.search.text().casefold()+'%';sql="SELECT k.id,k.title,coalesce(s.name,k.status) status_name,k.tags,k.urgency,k.created_at FROM kanban_tasks k LEFT JOIN task_statuses s ON s.code=k.status WHERE LOWER(k.title||' '||coalesce(k.description,'')||' '||coalesce(s.name,k.status)||' '||coalesce(k.tags,'')) LIKE ?";params=[q]
        if self.status.currentData():sql+=' AND k.status=?';params.append(self.status.currentData())
        if self.tag.currentData():sql+=' AND EXISTS(SELECT 1 FROM task_tag_links l WHERE l.task_id=k.id AND l.tag_id=?)';params.append(self.tag.currentData())
        if self.archive.currentIndex()<2:sql+=' AND k.is_archived=?';params.append(self.archive.currentIndex())
        rows=self.pager.fetch(sql+' ORDER BY k.id DESC',params);self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row[1:]):item=QTableWidgetItem(str(value or ''));item.setData(Qt.ItemDataRole.UserRole,row[0]);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(r,c,item)
    def load_boards(self):self.load_data()

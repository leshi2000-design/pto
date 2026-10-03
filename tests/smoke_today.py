import os,sys,tempfile
from pathlib import Path
folder=tempfile.TemporaryDirectory();os.environ['SMETAGAZ_DATA_DIR']=folder.name;os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import date,timedelta
from PyQt6.QtWidgets import QApplication,QMessageBox
from PyQt6.QtCore import Qt
app=QApplication([])
from smetagaz.theme import apply
apply(app)
def warning(*a,**k):raise AssertionError(str(a[1:]))
QMessageBox.warning=warning
from smetagaz.database import db
db.init_db()
from smetagaz.tasks_view import TaskEditDialog
from smetagaz.today_view import TodayView,RecurringDialog,RecurringEditDialog
from smetagaz.task_catalog import CatalogDialog
today=date.today()
# задача со сроком в прошлом сохраняется и помечается как просроченная
dlg=TaskEditDialog();dlg.inp_title.setText('Просрочено');dlg.set_due(dlg.dt_due.date().addDays(-2));assert 'Просрочено на 2 дня' in dlg.lbl_due.text();dlg.save_task()
assert db.fetchone("SELECT due_date FROM kanban_tasks WHERE title='Просрочено'")[0]==(today-timedelta(days=2)).isoformat()
# ежемесячная дата
edit=RecurringEditDialog();edit.title.setText('Зарплата');edit.day.setValue(10);edit.save()
assert RecurringDialog().table.rowCount()==1
# сам экран
view=TodayView();view.show();view.load_data();app.processEvents()
assert view.chip_overdue.value.text()=='1' and any('Просрочено' in t for t in view.day.texts())
marks=view.panel.calendar.marks;assert (today-timedelta(days=2)).isoformat() in marks and 'overdue' in marks[(today-timedelta(days=2)).isoformat()]
assert any('Зарплата' in e['title'] for e in __import__('smetagaz.agenda_domain',fromlist=['x']).events_between(db,today.replace(day=1),today.replace(day=1)+timedelta(days=40)))
# выбор другого дня и скрытие вида событий через легенду
view.select_day(today-timedelta(days=2));assert any('Просрочено' in t for t in view.day.texts())
view.panel.legend_buttons[0].setChecked(False);view.load_day();assert not any('Просрочено' in t for t in view.day.texts())
view.panel.legend_buttons[0].setChecked(True);view.load_day();assert any('Просрочено' in t for t in view.day.texts())
# справочник: новый статус и тег
cat=CatalogDialog();page=cat.statuses;page.start_new();page.name.setText('На согласовании');page.set_color('#7C3AED');page.done.setChecked(False);page.save()
assert db.fetchone("SELECT color FROM task_statuses WHERE name='На согласовании'")[0].upper()=='#7C3AED'
tags=cat.tags;tags.start_new();tags.name.setText('Срочно');tags.set_color('#DC2626');tags.save();assert db.fetchone("SELECT color FROM task_tags WHERE name='Срочно'")[0].upper()=='#DC2626'
view.tabs.setCurrentIndex(1);view.board.rebuild_columns();view.board.load_boards();assert any(t.text().startswith('НА СОГЛАСОВАНИИ') for t in view.board.titles.values())
view.tabs.setCurrentIndex(2);app.processEvents()
if os.environ.get('SMETAGAZ_TODAY_SCREENSHOT'):view.tabs.setCurrentIndex(0);assert view.grab().save(os.environ['SMETAGAZ_TODAY_SCREENSHOT'])
print('TODAY GUI OK: due dates, overdue marks, calendar markers, monthly dates, tag/status catalog')
view.close();cat.close()

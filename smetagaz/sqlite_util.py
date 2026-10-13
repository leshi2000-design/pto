"""Соединение SQLite, которое гарантированно закрывается: `with sqlite3.connect()` только фиксирует транзакцию и оставляет файл открытым,
а Windows не позволяет удалять и переименовывать открытые файлы (WinError 32)."""
import sqlite3
from contextlib import contextmanager


@contextmanager
def connect(path, **kwargs):
    con = sqlite3.connect(path, **kwargs)
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()

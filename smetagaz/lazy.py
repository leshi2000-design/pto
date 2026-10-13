"""Ленивый импорт тяжёлых библиотек (pandas, pyqtgraph): модуль подгружается при первом обращении, а не при запуске программы."""
import importlib


class LazyModule:
    def __init__(self, name):
        self.__dict__['_name'] = name
        self.__dict__['_module'] = None

    def _load(self):
        if self.__dict__['_module'] is None:
            self.__dict__['_module'] = importlib.import_module(self.__dict__['_name'])
        return self.__dict__['_module']

    def __getattr__(self, item):
        return getattr(self._load(), item)

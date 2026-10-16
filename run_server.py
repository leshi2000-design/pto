"""Запуск ПТО Сервера: python run_server.py   (или PTO_Server.exe после сборки)."""
import sys

from smetagaz.server_main import main

if __name__ == '__main__':
    sys.exit(main())

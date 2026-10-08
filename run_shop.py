"""Standalone Магазин entry point; separate database from СМЕТА-ГАЗ."""
import argparse
import os
from pathlib import Path
import sys
from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox
from shop.ui import Window


def main():
    parser = argparse.ArgumentParser(description='Магазин')
    parser.add_argument('--data-dir', default=os.environ.get('MAGAZIN_DATA_DIR', str(Path.home() / '.magazin')))
    args = parser.parse_args()
    root = Path(args.data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    lock = QLockFile(str(root / 'app.lock'))
    if not lock.tryLock(100):
        QMessageBox.warning(None, 'Магазин', 'Эта папка данных уже открыта другим экземпляром программы.')
        return 1
    window = Window(root)
    window.show()
    result = app.exec()
    lock.unlock()
    return result


if __name__ == '__main__':
    sys.exit(main())

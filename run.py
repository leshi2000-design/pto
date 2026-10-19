"""Launch before importing configuration; supports an isolated data directory."""
import argparse
import os
from pathlib import Path
parser=argparse.ArgumentParser(description='ПТО')
parser.add_argument('--data-dir',help='Папка с smetagaz.db, clients.db и вложениями')
parser.add_argument('--selftest',action='store_true',help='проверка сборки: результат в selftest.txt рядом с программой')
args=parser.parse_args()
if args.selftest:
    from smetagaz.selftest import run
    raise SystemExit(run())
if args.data_dir:os.environ['SMETAGAZ_DATA_DIR']=str(Path(args.data_dir).resolve())
from smetagaz.main_window import main
main()

"""Launch before importing configuration; supports an isolated data directory."""
import argparse
import os
from pathlib import Path
parser=argparse.ArgumentParser(description='СМЕТА-ГАЗ')
parser.add_argument('--data-dir',help='Папка с smetagaz.db, clients.db и вложениями')
args=parser.parse_args()
if args.data_dir:os.environ['SMETAGAZ_DATA_DIR']=str(Path(args.data_dir).resolve())
from smetagaz.main_window import main
main()

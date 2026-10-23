"""Launch before importing configuration; supports an isolated data directory."""
import argparse
import os
import sys
from pathlib import Path
parser=argparse.ArgumentParser(description='ПТО')
parser.add_argument('--data-dir',help='Папка с smetagaz.db, clients.db и вложениями')
parser.add_argument('--selftest',action='store_true',help='проверка сборки: результат в selftest.txt рядом с программой')
args=parser.parse_args()
if args.data_dir:os.environ['SMETAGAZ_DATA_DIR']=str(Path(args.data_dir).resolve())


def _start():
    if args.selftest:
        from smetagaz.selftest import run
        return run()
    from smetagaz.main_window import main
    main()


try:
    from smetagaz.startup import guarded
except BaseException:                       # даже сам модуль защиты не импортировался (повреждённая сборка) — пишем отчёт без него
    import traceback
    text=traceback.format_exc()
    for folder in (Path(sys.executable).parent,Path.home()/'.smetagaz'):
        try:
            folder.mkdir(parents=True,exist_ok=True);(folder/'startup_error.txt').write_text(text,encoding='utf-8')
        except Exception:pass
    raise SystemExit(1)
raise SystemExit(guarded(_start))

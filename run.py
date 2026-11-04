"""Launch before importing configuration; supports an isolated data directory."""
import argparse
import os
import sys
import traceback
from pathlib import Path
parser=argparse.ArgumentParser(description='ПТО')
parser.add_argument('--data-dir',help='Папка с smetagaz.db, clients.db и вложениями')
parser.add_argument('--selftest',action='store_true',help='проверка сборки: результат в selftest.txt рядом с программой')
args=parser.parse_args()
if args.data_dir:os.environ['SMETAGAZ_DATA_DIR']=str(Path(args.data_dir).resolve())

import pto_overlay                          # обновление из ZIP: подключается до первого импорта smetagaz
try:
    pto_overlay.activate()
except Exception:
    pto_overlay.deactivate(traceback.format_exc())


def _fallback_to_builtin(text):
    """Установленное обновление не запустилось: оно отключается, программа стартует заново со встроенной версией."""
    if pto_overlay.ACTIVE and not args.selftest and not os.environ.get('PTO_OVERLAY_FALLBACK'):
        pto_overlay.deactivate('Обновление ' + pto_overlay.ACTIVE['version'] + ' не запустилось и отключено:\n' + text)
        pto_overlay.relaunch({'PTO_OVERLAY_FALLBACK': '1'})
        return True
    return False


def _start():
    if args.selftest:
        from smetagaz.selftest import run
        return run()
    from smetagaz.main_window import main
    main()


def _start_with_fallback():
    try:
        return _start()
    except SystemExit:
        raise
    except BaseException:
        if _fallback_to_builtin(traceback.format_exc()):
            return 0
        raise


try:
    from smetagaz.startup import guarded
except BaseException:                       # даже сам модуль защиты не импортировался (повреждённая сборка или обновление)
    text=traceback.format_exc()
    if _fallback_to_builtin(text):
        raise SystemExit(0)
    for folder in (Path(sys.executable).parent,Path.home()/'.smetagaz'):
        try:
            folder.mkdir(parents=True,exist_ok=True);(folder/'startup_error.txt').write_text(text,encoding='utf-8')
        except Exception:pass
    raise SystemExit(1)
raise SystemExit(guarded(_start_with_fallback))

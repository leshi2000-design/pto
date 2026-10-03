"""Stable, private data directory; override with SMETAGAZ_DATA_DIR."""
import os
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
DATA_DIR = Path(os.environ.get("SMETAGAZ_DATA_DIR", Path.home() / ".smetagaz")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
DB_NAME = str(DATA_DIR / "smetagaz.db")
logging.basicConfig(handlers=[RotatingFileHandler(DATA_DIR / "app.log", maxBytes=1048576, backupCount=5, encoding="utf-8")], level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")





# scripts/logger.py

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import logging


# --------------------------------------------------
# CONFIG
# --------------------------------------------------
IST = ZoneInfo("Asia/Kolkata")

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "nifty_engine.log"


# --------------------------------------------------
# IST TIMESTAMP FORMATTER
# --------------------------------------------------
class ISTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, IST)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


# --------------------------------------------------
# LOGGER FACTORY
# --------------------------------------------------
def get_logger(name: str) -> logging.Logger:
    """
    Returns a singleton logger instance.

    Guarantees:
    - No duplicate handlers
    - No root propagation duplication
    - Stable across evaluator loops & subprocess imports
    """

    logger = logging.getLogger(name)

    # If already configured → reuse safely
    if logger.handlers:
        # ensure file handler exists
        has_file = any(isinstance(h, logging.FileHandler) for h in logger.handlers)

        if not has_file:
            file_handler = logging.FileHandler(LOG_FILE)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        return logger

    logger.setLevel(logging.INFO)

    # CRITICAL: prevent double logging via root logger
    logger.propagate = False

    formatter = ISTFormatter(
        "%(asctime)s | %(name)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    # ---------- File handler ----------
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)

    # ---------- Console handler ----------
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
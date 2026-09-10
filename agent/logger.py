import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FILE = Path.cwd() / "app.log"


def _build_logger() -> logging.Logger:
    log = logging.getLogger("agent")
    if log.handlers:
        return log

    log.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        _LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    log.addHandler(file_handler)
    log.addHandler(stream_handler)
    return log


logger = _build_logger()

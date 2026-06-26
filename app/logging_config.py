from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
BACKEND_LOG_NAME = "backend.log"
_HANDLER_MARKER = "_whatsapp_backend_file_handler"


def configure_backend_logging(logs_root: Path) -> Path:
    """Configure process-wide backend file logging.

    Uvicorn may already own console handlers. This adds a single rotating file handler
    to the root logger so app logs, FastAPI errors, and uvicorn logs land in one file.
    """
    logs_root.mkdir(parents=True, exist_ok=True)
    log_path = logs_root / BACKEND_LOG_NAME
    log_path.touch(exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    existing_handlers = [
        handler
        for handler in root_logger.handlers
        if getattr(handler, _HANDLER_MARKER, False)
    ]
    for handler in existing_handlers:
        if Path(getattr(handler, "baseFilename", "")) == log_path:
            return log_path
        root_logger.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    setattr(file_handler, _HANDLER_MARKER, True)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(file_handler)
    logging.getLogger("app").info("backend logging initialized path=%s", log_path)
    return log_path

# core/logging_config.py
import logging
from logging.handlers import RotatingFileHandler
import os

_LOGGER_NAME = "equidam"

def _ensure_logs_dir():
    os.makedirs("logs", exist_ok=True)

def get_logger(name: str = _LOGGER_NAME) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured
    _ensure_logs_dir()

    # Start at DEBUG level - handlers will filter
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")

    # Console handler - starts at INFO, can be changed to DEBUG
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    # File handler - always captures DEBUG
    fh = RotatingFileHandler("logs/app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.propagate = False
    return logger

def set_log_level(level_str: str) -> None:
    """
    Set the logging level for console output.
    File logging always remains at DEBUG level.
    
    Parameters
    ----------
    level_str : str
        'DEBUG' or 'INFO'
    """
    level = getattr(logging, level_str.upper(), logging.INFO)
    
    # Get the root equidam logger
    logger = logging.getLogger(_LOGGER_NAME)
    
    # Update all child loggers
    for name in logging.Logger.manager.loggerDict:
        if name.startswith(_LOGGER_NAME):
            child_logger = logging.getLogger(name)
            # Update console handlers only
            for h in child_logger.handlers:
                if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler):
                    h.setLevel(level)
"""
Agent Logger — Centralized logging system
Logs to:
  1. Console (colored)
  2. data/logs/agent_YYYYMMDD.log (file, daily rotation)
  3. WebSocket → dashboard live log panel
"""

import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# ─── CONSOLE COLORS ───────────────────────────────────────────
class ColorFormatter(logging.Formatter):
    COLORS = {
        'DEBUG':    '\033[90m',   # grey
        'INFO':     '\033[36m',   # cyan
        'WARNING':  '\033[33m',   # yellow
        'ERROR':    '\033[31m',   # red
        'CRITICAL': '\033[35m',   # magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, '')
        record.msg = f"{color}[{record.levelname[:4]}]{self.RESET} {record.msg}"
        return super().format(record)


def get_logger(name: str = 'agent') -> logging.Logger:
    """
    Get (or create) a named logger with file + console handlers.
    Call once per module: logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)

    # ── File handler (daily rotation, keep 30 days) ───────────
    log_file = os.path.join(LOG_DIR, 'agent.log')
    fh = TimedRotatingFileHandler(
        log_file,
        when='midnight',
        backupCount=30,
        encoding='utf-8',
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(fh)

    # ── Console handler ───────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(ColorFormatter(
        '%(asctime)s %(message)s',
        datefmt='%H:%M:%S'
    ))
    logger.addHandler(ch)

    # Don't propagate to root logger
    logger.propagate = False
    return logger


def get_log_files() -> list:
    """Return list of log files for the /logs API endpoint."""
    try:
        files = sorted(
            [f for f in os.listdir(LOG_DIR) if f.endswith('.log')],
            reverse=True
        )
        return [os.path.join(LOG_DIR, f) for f in files[:10]]
    except Exception:
        return []


def read_log_tail(n_lines: int = 200) -> list:
    """Read last N lines from today's log file."""
    log_file = os.path.join(LOG_DIR, 'agent.log')
    if not os.path.exists(log_file):
        return []
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n_lines:]]
    except Exception:
        return []

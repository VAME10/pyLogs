"""Logger: one CSV log file per run, console output, optional email alerts.

Call setup_logging() once, at the very start of your program:

    from logger import setup_logging
    import logging

    setup_logging()
    log = logging.getLogger(__name__)
    log.info("Hello")

Run this file directly for a demo: python logger.py
"""

import csv
import io
import itertools
import logging
import os
import sys
from collections import Counter
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from email_alerts import LOG_FORMAT, email_handler

# Skip per-record work for fields we never log. This turns off the stack walk
# and the thread/process lookups, so %(lineno)d, %(threadName)s etc. won't work.
logging._srcfile = None
logging.logThreads = logging.logProcesses = logging.logMultiprocessing = False

LOG_DIR = Path("logs")
KEEP_LOGS = 20
VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
LOG_PATTERN = "????-??-??_??-??-??*.csv"  # what create_log_file makes
COLUMNS = ["time", "level", "name", "message", "exception"]


class CsvFormatter(logging.Formatter):
    def __init__(self):
        super().__init__()
        # One reusable buffer and writer; the handler's lock makes this safe.
        self._buffer = io.StringIO()
        self._writer = csv.writer(self._buffer, lineterminator="")

    def format(self, record):
        self._buffer.seek(0)
        self._buffer.truncate()
        self._writer.writerow([
            datetime.fromtimestamp(record.created).isoformat(sep=" ", timespec="milliseconds"),
            record.levelname,
            record.name,
            record.getMessage(),
            self.formatException(record.exc_info) if record.exc_info else "",
        ])
        return self._buffer.getvalue()


def create_log_dir(log_dir=LOG_DIR):
    """Create the logs directory if it doesn't already exist, and return its Path."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _next_number(log_dir, stamp):
    """One more than the highest suffix already used this second (0 means no suffix)."""
    used = []
    for existing in log_dir.glob(f"{stamp}*.csv"):
        tail = existing.stem[len(stamp):]  # "" or "_001"
        if tail == "":
            used.append(0)
        elif tail.startswith("_") and tail[1:].isdigit():
            used.append(int(tail[1:]))
    return max(used, default=-1) + 1


def create_log_file(log_dir=LOG_DIR):
    """Create a new timestamped CSV file (with header row) in log_dir, and return its Path.

    Never overwrites: if a run already made a file this second, a numbered suffix
    is added (..._001.csv, ..._002.csv). Numbers only ever go up, so file names
    always sort oldest to newest, even after old files have been cleaned up.
    """
    log_dir = Path(log_dir)
    stamp = f"{datetime.now():%Y-%m-%d_%H-%M-%S}"
    for number in itertools.count(_next_number(log_dir, stamp)):
        suffix = f"_{number:03d}" if number else ""
        log_file = log_dir / f"{stamp}{suffix}.csv"
        try:
            # mode "x" creates the file or fails: it can never truncate an existing one
            with log_file.open("x", newline="", encoding="utf-8") as f:
                csv.writer(f, lineterminator="\n").writerow(COLUMNS)
        except FileExistsError:
            continue
        return log_file


def _file_handler(log_file):
    handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    handler.setFormatter(CsvFormatter())
    return handler


def _console_handler():
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def _cleanup(log_dir, keep, current):
    """Keep the newest `keep` log files. The file being written (current) is never deleted."""
    others = sorted(f for f in log_dir.glob(LOG_PATTERN) if f != current)
    for old in others[:max(len(others) - (keep - 1), 0)]:
        with suppress(OSError):  # in use elsewhere, or already deleted by another run
            old.unlink()


def _log_uncaught(exc_type, exc, tb):
    """sys.excepthook: write crashes to the log file too, not just the terminal."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("uncaught").critical("Uncaught exception", exc_info=(exc_type, exc, tb))


def setup_logging(log_dir=LOG_DIR, keep=KEEP_LOGS):
    """Call once, at the very start of the program. Returns the new log file's Path."""
    requested = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = requested if requested in VALID_LEVELS else "INFO"

    log_dir = create_log_dir(log_dir)
    log_file = create_log_file(log_dir)

    handlers = [_file_handler(log_file), _console_handler(), email_handler()]
    logging.basicConfig(level=level, handlers=[h for h in handlers if h], force=True)
    sys.excepthook = _log_uncaught
    if level != requested:
        logging.getLogger(__name__).warning("Unknown LOG_LEVEL %r, using INFO", requested)
    _cleanup(log_dir, keep, log_file)
    return log_file


# ---- reading / analyzing logs ----

def latest_log(log_dir=LOG_DIR):
    return max(Path(log_dir).glob(LOG_PATTERN), default=None)


def read_entries(path):
    with Path(path).open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def filter_level(entries, level):
    return (e for e in entries if e["level"] == level.upper())


def count_levels(entries):
    return Counter(e["level"] for e in entries)


if __name__ == "__main__":
    log_file = setup_logging()  # first thing that runs
    print("Logging to:", log_file.resolve())
    log = logging.getLogger(__name__)

    log.info("Program started")
    log.debug("Only visible with LOG_LEVEL=DEBUG")
    try:
        1 / 0
    except ZeroDivisionError:
        log.exception("Demo error")
    log.info("Program finished")

    print(f"\nLog file: {log_file}")
    print(count_levels(read_entries(log_file)))

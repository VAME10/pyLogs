"""Logger: one CSV log file per run, console output, optional email alerts.

Call setup_logging() once, at the very start of your program:

    from logger import setup_logging
    import logging

    setup_logging()
    log = logging.getLogger(__name__)
    log.info("Hello")

Set the LOG_LEVEL environment variable (DEBUG, INFO, WARNING, ERROR, CRITICAL)
to change the verbosity; the default is INFO. Requires Python 3.8+.

Run this file directly for a demo: python logger.py
"""

from __future__ import annotations

import csv
import io
import itertools
import logging
import os
import sys
import threading
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from email_alerts import email_handler

LOG_DIR = Path("logs")
KEEP_LOGS = 20
VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
LOG_PATTERN = "????-??-??_??-??-??*.csv"  # what create_log_file makes
COLUMNS = ["time", "level", "name", "message", "exception"]
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


class CsvFormatter(logging.Formatter):
    """Format a record as one CSV row (see COLUMNS)."""

    def format(self, record: logging.LogRecord) -> str:
        row = [
            datetime.fromtimestamp(record.created).isoformat(sep=" ", timespec="milliseconds"),
            record.levelname,
            record.name,
            record.getMessage(),
            self.formatException(record.exc_info) if record.exc_info else "",
        ]
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="").writerow(row)
        return buffer.getvalue()


def create_log_dir(log_dir: str | Path = LOG_DIR) -> Path:
    """Create the logs directory if it doesn't already exist, and return its Path."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _next_number(log_dir: Path, stamp: str) -> int:
    """One more than the highest suffix already used this second (0 means no suffix)."""
    used = []
    for existing in log_dir.glob(f"{stamp}*.csv"):
        tail = existing.stem[len(stamp):]  # "" or "_001"
        if tail == "":
            used.append(0)
        elif tail.startswith("_") and tail[1:].isdigit():
            used.append(int(tail[1:]))
    return max(used, default=-1) + 1


def create_log_file(log_dir: str | Path = LOG_DIR) -> Path:
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


def _file_handler(log_file: Path) -> logging.Handler:
    handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    handler.setFormatter(CsvFormatter())
    return handler


def _console_handler() -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    return handler


def _cleanup(log_dir: Path, keep: int, current: Path) -> None:
    """Keep the newest `keep` log files. The file being written (current) is never deleted."""
    others = sorted(f for f in log_dir.glob(LOG_PATTERN) if f != current)
    for old in others[:max(len(others) - (keep - 1), 0)]:
        with suppress(OSError):  # in use elsewhere, or already deleted by another run
            old.unlink()


def _log_uncaught(exc_type, exc, tb) -> None:
    """sys.excepthook: write crashes to the log file too, not just the terminal."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("uncaught").critical("Uncaught exception", exc_info=(exc_type, exc, tb))


def _log_thread_crash(args: threading.ExceptHookArgs) -> None:
    """threading.excepthook: the same, for exceptions that kill a background thread."""
    if args.exc_type is SystemExit:  # a thread exiting normally, as in the default hook
        return
    name = args.thread.name if args.thread else "unknown"
    logging.getLogger("uncaught").critical(
        "Uncaught exception in thread %s", name,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def setup_logging(log_dir: str | Path = LOG_DIR, keep: int = KEEP_LOGS) -> Path:
    """Call once, at the very start of the program. Returns the new log file's Path."""
    requested = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = requested if requested in VALID_LEVELS else "INFO"

    log_dir = create_log_dir(log_dir)
    log_file = create_log_file(log_dir)

    handlers = [_file_handler(log_file), _console_handler(), email_handler()]
    logging.basicConfig(level=level, handlers=[h for h in handlers if h], force=True)
    logging.captureWarnings(True)  # warnings.warn() messages go to the log too
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_thread_crash
    if level != requested:
        logging.getLogger(__name__).warning("Unknown LOG_LEVEL %r, using INFO", requested)
    _cleanup(log_dir, keep, log_file)
    return log_file


# ---- reading / analyzing logs ----

def latest_log(log_dir: str | Path = LOG_DIR) -> Path | None:
    """Return the newest log file, or None if there are none."""
    return max(Path(log_dir).glob(LOG_PATTERN), default=None)


def read_entries(path: str | Path) -> Iterator[dict[str, str]]:
    """Yield each log row as a dict keyed by COLUMNS."""
    with Path(path).open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def filter_level(entries: Iterable[dict[str, str]], level: str) -> Iterator[dict[str, str]]:
    """Yield only the entries logged at `level`."""
    return (e for e in entries if e["level"] == level.upper())


def count_levels(entries: Iterable[dict[str, str]]) -> Counter:
    """Count entries per level, e.g. Counter({'INFO': 2, 'ERROR': 1})."""
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

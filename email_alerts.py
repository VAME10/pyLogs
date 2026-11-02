"""Email alerts for the logger: one email per ERROR or CRITICAL record.

Alerts are off unless these environment variables are set:

    ALERT_SMTP_HOST   mail server (required)
    ALERT_TO          recipient address (required)
    ALERT_SMTP_PORT   default 587
    ALERT_USER        login name (enables TLS and authentication)
    ALERT_PASSWORD    login password
    ALERT_FROM        sender address (defaults to ALERT_USER)

Emails are sent on a background thread, so a slow mail server never blocks
your program, and at most one is sent per ALERT_INTERVAL seconds, so an error
inside a loop doesn't flood your inbox (the log file still gets every error).
"""

import atexit
import logging
import os
import queue
from logging.handlers import QueueHandler, QueueListener, SMTPHandler

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
ALERT_INTERVAL = 60  # seconds


class RateLimit(logging.Filter):
    """Let one record through every `seconds`; drop the rest."""

    def __init__(self, seconds=ALERT_INTERVAL):
        super().__init__()
        self.seconds = seconds
        self._last = float("-inf")

    def filter(self, record):
        if record.created - self._last < self.seconds:
            return False
        self._last = record.created
        return True


def _smtp_handler():
    """Return an SMTPHandler for errors, or None if alerts aren't configured."""
    host, to = os.environ.get("ALERT_SMTP_HOST"), os.environ.get("ALERT_TO")
    if not (host and to):
        return None  # alerts are off unless configured
    user = os.environ.get("ALERT_USER")
    handler = SMTPHandler(
        mailhost=(host, int(os.environ.get("ALERT_SMTP_PORT", 587))),
        fromaddr=os.environ.get("ALERT_FROM", user or "logger@localhost"),
        toaddrs=[to],
        subject="Application error",
        credentials=(user, os.environ.get("ALERT_PASSWORD", "")) if user else None,
        secure=() if user else None,
    )
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def _in_background(handler):
    """Wrap a slow handler so logging calls return immediately."""
    records = queue.SimpleQueue()
    # respect_handler_level: without it the listener ignores the handler's level
    listener = QueueListener(records, handler, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)  # sends anything still queued when the program exits
    queued = QueueHandler(records)
    queued.setLevel(handler.level)  # don't even queue records that would be dropped
    queued.addFilter(RateLimit())  # rate-limited records never enter the queue
    return queued


def email_handler():
    """Return the handler for email alerts, or None if alerts aren't configured."""
    handler = _smtp_handler()
    return _in_background(handler) if handler else None

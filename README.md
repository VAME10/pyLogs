What it does

Creates a new log file on every run. Files are CSV, so you can open them in a spreadsheet or analyze them with code. They are timestamped and saved in a logs/ folder.
Prints to the console. You see the same messages live in the terminal.
Cleans up old logs. It keeps the newest 20 files and deletes the rest.
Sends email alerts on errors. This is optional and only turns on if you set the email settings. Emails are sent in the background and limited to one per minute, except for crashes, which always send.
Logs crashes. Uncaught errors, including ones in background threads, are written to the log before the program stops.
Reads logs back. Helper functions find the newest log, read its rows, filter by level and count entries per level.
Controls verbosity with LOG_LEVEL. An environment variable sets how much gets logged. The default is INFO.

The files

logger.py holds the main code: setup, the CSV format, cleanup and the log-reading helpers.
email_alerts.py holds the optional email alerts.

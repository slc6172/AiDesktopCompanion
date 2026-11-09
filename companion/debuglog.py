"""Where the tuning ("debug") lines go: the console (what you see running run.bat) AND the log file
data/app.log. Both are needed: logging feeds the file, but a bare print() only reaches the file in the
windowed exe."""
import logging

log = logging.getLogger("companion.debug")


def default_log(line):
    print(line, flush=True)
    log.info(line)

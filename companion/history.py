import calendar
import sqlite3
import time
from contextlib import closing

NEUTRAL_AFFECTION = 50.0  # where every new relationship starts (and, later, drifts back towards)


def _parse_utc(text):
    """Epoch seconds for a "YYYY-MM-DD HH:MM:SS" UTC string, None for anything else."""
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%d %H:%M:%S")))
    except (TypeError, ValueError):
        return None


# The long-term memory's sections, in the order they are shown to her.
SECTIONS = ("使用者", "共同經歷", "角色自己的事", "待跟進", "更早的摘要")


class InMemoryHistory:
    """Default store: lives only as long as the process."""

    def __init__(self):
        self._messages = []
        self._times = []  # parallel to _messages: epoch seconds, or None when not known
        self._fold_progress = 0  # how many messages (from the start) have been folded into the long-term memory
        self._polluted = []  # parallel to _messages: did this turn use web content?
        self._facts = {}  # long-term memory: section -> text
        self._events = []  # the journal: {"date", "time", "kind", "text"}, append only
        self._affection = NEUTRAL_AFFECTION
        self._last_interaction = None

    def load(self):
        return [dict(m) for m in self._messages]

    def load_times(self):
        return list(self._times)

    def append_turn(self, user, assistant, at=None, polluted=False):
        self._messages.append({"role": "user", "content": user})
        self._messages.append({"role": "assistant", "content": assistant})
        self._times.extend([None if at is None else float(at)] * 2)
        self._polluted.extend([bool(polluted)] * 2)

    def load_polluted(self):
        return list(self._polluted)

    # ---- layered memory (spec Part 12, section 8) ----
    def load_facts(self):
        return dict(self._facts)

    def save_facts(self, facts):
        self._facts = dict(facts)

    def append_events(self, events):
        self._events.extend(dict(e) for e in events)

    def apply_fold(self, events, facts, summarized_messages):
        """The result of one fold, all at once: new journal events, the whole new set of facts (None =
        keep the old ones) and how far the folding has got."""
        self._events.extend(dict(e) for e in events)
        if facts is not None:
            self._facts = dict(facts)
        self._fold_progress = summarized_messages

    def load_events(self, dates):
        return [dict(e) for e in self._events if e["date"] in dates]

    def load_all_events(self):
        return [dict(e) for e in self._events]

    def load_fold_progress(self):
        return self._fold_progress

    # Affection is deliberately NOT part of the memory record above: the background summary
    # reads memory, spends a while in the LLM, then writes the whole record back, which would
    # silently overwrite an affection change made by a turn that finished in the meantime.
    # Its own write path (and, in SQLite, its own table) cannot be clobbered that way.
    def load_affection(self):
        return self._affection

    def save_affection(self, value, at=None):
        """`at` is the wall-clock time (epoch seconds) of the interaction this belongs to; left
        out, the previously recorded time is kept."""
        self._affection = float(value)
        if at is not None:
            self._last_interaction = float(at)

    def load_last_interaction(self):
        return self._last_interaction


class SqliteHistory:
    """Local SQLite store. A connection per call keeps it safe across threads."""

    def __init__(self, path):
        self._path = str(path)
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "role TEXT NOT NULL, content TEXT NOT NULL, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
                "polluted INTEGER NOT NULL DEFAULT 0)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS memory ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), summarized_messages INTEGER NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS relationship ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), affection REAL NOT NULL, last_interaction REAL)"
            )
            conn.execute("CREATE TABLE IF NOT EXISTS memory_facts (section TEXT PRIMARY KEY, text TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS memory_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "date TEXT NOT NULL, time TEXT, kind TEXT NOT NULL, text TEXT NOT NULL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS memory_events_date ON memory_events (date)")

    def load_polluted(self):
        with closing(sqlite3.connect(self._path)) as conn:
            rows = conn.execute("SELECT polluted FROM messages ORDER BY id").fetchall()
        return [bool(flag) for (flag,) in rows]

    def load_facts(self):
        with closing(sqlite3.connect(self._path)) as conn:
            rows = conn.execute("SELECT section, text FROM memory_facts").fetchall()
        return dict(rows)

    def save_facts(self, facts):
        with closing(sqlite3.connect(self._path)) as conn, conn:   # replaced as one set, or not at all
            conn.execute("DELETE FROM memory_facts")
            conn.executemany("INSERT INTO memory_facts (section, text) VALUES (?, ?)", list(facts.items()))

    def append_events(self, events):
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.executemany(
                "INSERT INTO memory_events (date, time, kind, text) VALUES (?, ?, ?, ?)",
                [(e["date"], e.get("time"), e["kind"], e["text"]) for e in events],
            )

    def apply_fold(self, events, facts, summarized_messages):
        """The result of one fold in ONE transaction: a crash cannot leave events written but the
        progress not moved (which would write the same events again)."""
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.executemany(
                "INSERT INTO memory_events (date, time, kind, text) VALUES (?, ?, ?, ?)",
                [(e["date"], e.get("time"), e["kind"], e["text"]) for e in events],
            )
            if facts is not None:
                conn.execute("DELETE FROM memory_facts")
                conn.executemany("INSERT INTO memory_facts (section, text) VALUES (?, ?)", list(facts.items()))
            conn.execute(
                "INSERT INTO memory (id, summarized_messages) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET summarized_messages = excluded.summarized_messages",
                (summarized_messages,),
            )

    def load_all_events(self):
        with closing(sqlite3.connect(self._path)) as conn:
            rows = conn.execute("SELECT date, time, kind, text FROM memory_events ORDER BY id").fetchall()
        return [{"date": d, "time": t, "kind": k, "text": x} for d, t, k, x in rows]

    def load_events(self, dates):
        dates = list(dates)
        if not dates:
            return []
        with closing(sqlite3.connect(self._path)) as conn:
            rows = conn.execute(
                f"SELECT date, time, kind, text FROM memory_events WHERE date IN ({', '.join('?' * len(dates))}) ORDER BY id",
                dates,
            ).fetchall()
        return [{"date": d, "time": t, "kind": k, "text": x} for d, t, k, x in rows]

    def load(self):
        with closing(sqlite3.connect(self._path)) as conn:
            rows = conn.execute("SELECT role, content FROM messages ORDER BY id").fetchall()
        return [{"role": role, "content": content} for role, content in rows]

    def load_times(self):
        """When each message was written, aligned one-to-one with load(): epoch seconds, or None
        where the time is missing or unreadable. (SQLite's CURRENT_TIMESTAMP is UTC.)"""
        with closing(sqlite3.connect(self._path)) as conn:
            rows = conn.execute("SELECT created_at FROM messages ORDER BY id").fetchall()
        return [_parse_utc(created_at) for (created_at,) in rows]

    def append_turn(self, user, assistant, at=None, polluted=False):
        """`at` is the epoch-seconds time of this turn; left out, SQLite stamps the rows itself
        (the same UTC text either way, so old and new rows read back the same way)."""
        flag = 1 if polluted else 0
        # One transaction: a turn is saved whole or not at all.
        with closing(sqlite3.connect(self._path)) as conn, conn:
            if at is None:
                conn.executemany(
                    "INSERT INTO messages (role, content, polluted) VALUES (?, ?, ?)",
                    [("user", user, flag), ("assistant", assistant, flag)],
                )
            else:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(at))
                conn.executemany(
                    "INSERT INTO messages (role, content, created_at, polluted) VALUES (?, ?, ?, ?)",
                    [("user", user, stamp, flag), ("assistant", assistant, stamp, flag)],
                )

    def load_fold_progress(self):
        with closing(sqlite3.connect(self._path)) as conn:
            row = conn.execute("SELECT summarized_messages FROM memory WHERE id = 1").fetchone()
        return 0 if row is None else int(row[0])

    def load_affection(self):
        with closing(sqlite3.connect(self._path)) as conn:
            row = conn.execute("SELECT affection FROM relationship WHERE id = 1").fetchone()
        return NEUTRAL_AFFECTION if row is None else float(row[0])

    def load_last_interaction(self):
        with closing(sqlite3.connect(self._path)) as conn:
            row = conn.execute("SELECT last_interaction FROM relationship WHERE id = 1").fetchone()
        return None if row is None or row[0] is None else float(row[0])

    def save_affection(self, value, at=None):
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(
                "INSERT INTO relationship (id, affection, last_interaction) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET affection = excluded.affection, "
                "last_interaction = COALESCE(excluded.last_interaction, relationship.last_interaction)",
                (float(value), None if at is None else float(at)),
            )

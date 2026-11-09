"""The character's own state, kept apart from the conversation history (spec Part 12).

Where she is, her body status, what she holds, what she is wearing and how many photos she has
taken today. The engine is the only writer; everything here is plain storage.
"""
import json
import sqlite3
from contextlib import closing

DEFAULT_LOCATION = "家裡"

_COLUMNS = ("outfit", "location", "status", "status_set_at", "items",
            "photo_day", "photo_count", "photo_exhausted_until")


def _defaults(default_location):
    return {
        "outfit": None, "location": default_location,
        "status": None, "status_set_at": None, "items": [],
        "photo_day": None, "photo_count": 0, "photo_exhausted_until": None,
    }


class InMemoryState:
    """Test double and offline-demo store: lives only as long as the process."""

    def __init__(self, default_location=DEFAULT_LOCATION):
        self.default_location = default_location
        self._values = {}

    def load(self):
        merged = _defaults(self.default_location)
        merged.update(self._values)
        merged["items"] = list(merged["items"])
        return merged

    def set_outfit(self, name):
        self._values["outfit"] = name

    def set_location(self, place):
        self._values["location"] = place

    def set_status(self, name, at=None):
        self._values["status"] = name
        self._values["status_set_at"] = None if name is None else at

    def set_items(self, items):
        self._values["items"] = list(items)

    def reset(self):
        """Back to a fresh start for everything EXCEPT the photo quota record."""
        for key in ("outfit", "location", "status", "status_set_at", "items"):
            self._values.pop(key, None)

    def record_photo(self, day):
        current = self.load()
        count = current["photo_count"] + 1 if current["photo_day"] == day else 1
        self._values.update(photo_day=day, photo_count=count)

    def set_photo_exhausted_until(self, epoch):
        self._values["photo_exhausted_until"] = epoch


class SqliteState:
    """One row in the same SQLite file as the history. A connection per call, like SqliteHistory."""

    def __init__(self, path, default_location=DEFAULT_LOCATION):
        self._path = str(path)
        self.default_location = default_location
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS companion_state ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), outfit TEXT, location TEXT, "
                "status TEXT, status_set_at REAL, items TEXT, "
                "photo_day TEXT, photo_count INTEGER, photo_exhausted_until REAL)"
            )

    def load(self):
        merged = _defaults(self.default_location)
        with closing(sqlite3.connect(self._path)) as conn:
            row = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM companion_state WHERE id = 1").fetchone()
        if row is not None:
            stored = dict(zip(_COLUMNS, row))
            for key, value in stored.items():
                if value is None:
                    continue  # never written: keep the default (and a NULL status means "normal")
                merged[key] = json.loads(value) if key == "items" else value
        return merged

    def _write(self, **values):
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns)
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(
                f"INSERT INTO companion_state (id, {', '.join(columns)}) VALUES (1, {placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                [values[c] for c in columns],
            )

    def set_outfit(self, name):
        self._write(outfit=name)

    def set_location(self, place):
        self._write(location=place)

    def set_status(self, name, at=None):
        self._write(status=name, status_set_at=None if name is None else at)

    def set_items(self, items):
        self._write(items=json.dumps(list(items), ensure_ascii=False))

    def reset(self):
        """Back to a fresh start for everything EXCEPT the photo quota record."""
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(
                "UPDATE companion_state SET outfit = NULL, location = NULL, status = NULL, "
                "status_set_at = NULL, items = NULL WHERE id = 1"
            )

    def record_photo(self, day):
        # One statement, so two photos finishing at once cannot lose a count.
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(
                "INSERT INTO companion_state (id, photo_day, photo_count) VALUES (1, ?, 1) "
                "ON CONFLICT(id) DO UPDATE SET "
                "photo_count = CASE WHEN photo_day = excluded.photo_day THEN COALESCE(photo_count, 0) + 1 ELSE 1 END, "
                "photo_day = excluded.photo_day",
                (day,),
            )

    def set_photo_exhausted_until(self, epoch):
        self._write(photo_exhausted_until=epoch)

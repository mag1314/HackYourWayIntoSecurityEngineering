"""SQLite ledger: guarantees a posting is never applied to twice."""
import sqlite3
from datetime import datetime
from .config import DATA_DIR

DB = DATA_DIR / "applications.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
  posting_id TEXT PRIMARY KEY,
  company    TEXT NOT NULL,
  title      TEXT NOT NULL,
  url        TEXT NOT NULL,
  status     TEXT NOT NULL,   -- discovered | generated | needs_input | applied | skipped
  notes      TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


class Tracker:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        self.con = sqlite3.connect(DB)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    def get(self, posting_id: str):
        return self.con.execute("SELECT * FROM applications WHERE posting_id=?", (posting_id,)).fetchone()

    def status(self, posting_id: str) -> str | None:
        row = self.get(posting_id)
        return row["status"] if row else None

    def upsert(self, posting_id: str, company: str, title: str, url: str, status: str, notes: str = ""):
        now = datetime.now().isoformat(timespec="seconds")
        self.con.execute("""
            INSERT INTO applications (posting_id, company, title, url, status, notes, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(posting_id) DO UPDATE SET status=excluded.status, notes=excluded.notes, updated_at=excluded.updated_at
        """, (posting_id, company, title, url, status, notes, now, now))
        self.con.commit()

    def set_status(self, posting_id: str, status: str, notes: str = ""):
        now = datetime.now().isoformat(timespec="seconds")
        self.con.execute("UPDATE applications SET status=?, notes=?, updated_at=? WHERE posting_id=?",
                         (status, notes, now, posting_id))
        self.con.commit()

    def by_status(self, *statuses: str):
        q = ",".join("?" * len(statuses))
        return self.con.execute(f"SELECT * FROM applications WHERE status IN ({q}) ORDER BY company, title",
                                statuses).fetchall()

    def all(self):
        return self.con.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()

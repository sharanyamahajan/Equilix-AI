# ledger.py
import sqlite3
import hashlib
import time
import json

class Ledger:
    def __init__(self, db_path="equilix.db"):
        self.db_path = db_path
        self._init()

    def _init(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ledger (
            idx INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            payload TEXT,
            prev_hash TEXT,
            hash TEXT
        )""")
        conn.commit()
        conn.close()

    def append(self, payload: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT hash FROM ledger ORDER BY idx DESC LIMIT 1")
        row = cur.fetchone()
        prev = row[0] if row else ""
        ts = time.time()
        blob = f"{ts}|{payload}|{prev}"
        h = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        cur.execute("INSERT INTO ledger (timestamp, payload, prev_hash, hash) VALUES (?, ?, ?, ?)",
                    (ts, payload, prev, h))
        conn.commit()
        conn.close()
        return h

    def read_latest(self, limit:int=50):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT idx, timestamp, payload, prev_hash, hash FROM ledger ORDER BY idx DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        conn.close()
        out = []
        for r in rows:
            out.append({"idx": r[0], "timestamp": r[1], "payload": r[2], "prev_hash": r[3], "hash": r[4]})
        return out

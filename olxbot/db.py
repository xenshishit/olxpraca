"""SQLite-сховище налаштувань користувачів і вже надісланих оголошень."""
import json
import sqlite3

DEFAULTS = {"city_id": None, "city_name": None, "min_salary": 0,
            "sort": "new", "subs": [], "exclude": []}


class DB:
    def __init__(self, path: str = "olxbot.db"):
        self.conn = sqlite3.connect(path)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, settings TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sent (user_id INTEGER, offer_id INTEGER,
                PRIMARY KEY (user_id, offer_id));
        """)

    def get(self, user_id: int) -> dict:
        row = self.conn.execute("SELECT settings FROM users WHERE id=?", (user_id,)).fetchone()
        return {**DEFAULTS, **(json.loads(row[0]) if row else {})}

    def save(self, user_id: int, settings: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO users VALUES (?, ?)",
                          (user_id, json.dumps(settings, ensure_ascii=False)))
        self.conn.commit()

    def subscribers(self) -> list[tuple[int, dict]]:
        rows = self.conn.execute("SELECT id, settings FROM users").fetchall()
        return [(uid, {**DEFAULTS, **json.loads(s)}) for uid, s in rows
                if json.loads(s).get("subs")]

    def filter_unsent(self, user_id: int, offer_ids: list[int]) -> set[int]:
        sent = {r[0] for r in self.conn.execute(
            "SELECT offer_id FROM sent WHERE user_id=?", (user_id,))}
        return set(offer_ids) - sent

    def mark_sent(self, user_id: int, offer_ids) -> None:
        self.conn.executemany("INSERT OR IGNORE INTO sent VALUES (?, ?)",
                              [(user_id, i) for i in offer_ids])
        self.conn.commit()

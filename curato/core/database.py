import sqlite3
from pathlib import Path

class Database:
    def __init__(self, db_path="curato.db"):
        self.db_path = db_path

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with self.get_connection() as conn:
            conn.executescript(schema_sql)
        print(f"Database initialized at {self.db_path}")

    def insert_items(self, items):
        if not items:
            return
        query = """
            INSERT OR IGNORE INTO feed_items 
            (id, title, normalized_title, url, canonical_url, url_hash, source, language, snippet, category, created_at, collected_at, comment_count, upvote_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        data = [
            (i.id, i.title, i.normalized_title, i.url, i.canonical_url, i.url_hash, i.source, 
             i.language, i.snippet, i.category, i.created_at, i.collected_at, i.comment_count, i.upvote_count)
            for i in items
        ]
        with self.get_connection() as conn:
            conn.executemany(query, data)
            conn.commit()

def get_db(db_path="curato.db"):
    db = Database(db_path)
    db.init_db()
    return db

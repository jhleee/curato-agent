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

    def get_recent_items(self, hours: int = 24):
        from curato.core.models import FeedItem
        from datetime import datetime, timedelta
        
        since = datetime.now() - timedelta(hours=hours)
        query = """
            SELECT id, title, normalized_title, url, canonical_url, url_hash, source, 
                   language, snippet, category, created_at, collected_at, comment_count, upvote_count
            FROM feed_items
            WHERE collected_at >= ?
        """
        
        items = []
        with self.get_connection() as conn:
            # sqlite returns datetime as string if not using PARSE_DECLTYPES
            for row in conn.execute(query, (since.strftime("%Y-%m-%d %H:%M:%S"),)):
                created_dt = datetime.strptime(row[10].split('.')[0], "%Y-%m-%d %H:%M:%S") if row[10] else None
                collected_dt = datetime.strptime(row[11].split('.')[0], "%Y-%m-%d %H:%M:%S") if row[11] else datetime.now()
                items.append(FeedItem(
                    id=row[0], title=row[1], normalized_title=row[2], url=row[3], canonical_url=row[4],
                    url_hash=row[5], source=row[6], language=row[7], snippet=row[8], category=row[9],
                    created_at=created_dt, collected_at=collected_dt, comment_count=row[12], upvote_count=row[13]
                ))
        return items

def get_db(db_path="curato.db"):
    db = Database(db_path)
    db.init_db()
    return db

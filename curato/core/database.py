import sqlite3
from pathlib import Path

class Database:
    def __init__(self, db_path="curato.db"):
        self.db_path = db_path

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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
                created_dt = datetime.strptime(str(row[10])[:19], "%Y-%m-%d %H:%M:%S") if row[10] else None
                collected_dt = datetime.strptime(str(row[11])[:19], "%Y-%m-%d %H:%M:%S") if row[11] else datetime.now()
                items.append(FeedItem(
                    id=row[0], title=row[1], normalized_title=row[2], url=row[3], canonical_url=row[4],
                    url_hash=row[5], source=row[6], language=row[7], snippet=row[8], category=row[9],
                    created_at=created_dt, collected_at=collected_dt, comment_count=row[12], upvote_count=row[13]
                ))
        return items

    def save_pipeline_results(self, run_id: str, clusters: list[dict]):
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        run_query = """
            INSERT INTO pipeline_runs (run_id, started_at, finished_at, status)
            VALUES (?, ?, ?, 'completed')
        """
        
        cluster_query = """
            INSERT INTO clusters (
                cluster_id, run_id, created_at, cohesion, volume,
                trend_score, final_label, one_line_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """

        cluster_item_query = """
            INSERT OR IGNORE INTO cluster_items (cluster_id, item_id, is_representative)
            VALUES (?, ?, ?)
        """

        with self.get_connection() as conn:
            conn.execute(run_query, (run_id, now_str, now_str))
            
            for c in clusters:
                c_id = c['cluster_id']
                score = c.get('trend_score', 0)
                vol = c.get('size', 0)
                cohesion = c.get('cohesion', 0)
                label = c.get('final_label', '')
                summary = c.get('one_line_summary', '')
                
                conn.execute(cluster_query, (c_id, run_id, now_str, cohesion, vol, score, label, summary))
                
                # items
                for item in c.get('items', []):
                    # For simplicity, we just save the item mapping
                    conn.execute(cluster_item_query, (c_id, item.id, 0))
            conn.commit()

    def get_clusters(self, limit: int = 50):
        query = """
            SELECT cluster_id, run_id, created_at, trend_score, volume, cohesion, final_label, one_line_summary
            FROM clusters
            ORDER BY created_at DESC, trend_score DESC
            LIMIT ?
        """
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute(query, (limit,)).fetchall()]

    def get_cluster_items(self, cluster_id: str):
        query = """
            SELECT f.title, f.url, f.source, f.created_at
            FROM cluster_items ci
            JOIN feed_items f ON ci.item_id = f.id
            WHERE ci.cluster_id = ?
        """
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute(query, (cluster_id,)).fetchall()]

def get_db(db_path="curato.db"):
    db = Database(db_path)
    db.init_db()
    return db

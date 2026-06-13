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

def get_db(db_path="curato.db"):
    db = Database(db_path)
    db.init_db()
    return db

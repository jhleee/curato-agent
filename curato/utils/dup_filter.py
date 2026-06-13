import sqlite3

class DuplicateFilter:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def is_already_collected(self, url_hash: str) -> bool:
        """URL hash 기반 이미 수집된 아이템 여부 확인"""
        with sqlite3.connect(self.db_path) as conn:
            # 테이블이 없을 수도 있으므로 예외 처리 추가
            try:
                row = conn.execute(
                    "SELECT 1 FROM feed_items WHERE url_hash = ?",
                    (url_hash,)
                ).fetchone()
                return row is not None
            except sqlite3.OperationalError:
                # 테이블이 아직 생성되지 않은 경우 등
                return False

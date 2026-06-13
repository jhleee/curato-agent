from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class FeedItem:
    id: str              # URL hash SHA256 앞 16자리
    title: str           # 원본 제목
    normalized_title: str# 정규화 제목
    url: str             # 원본 URL
    canonical_url: str   # 정규화 URL
    url_hash: str        # SHA256(canonical_url)
    source: str          # 출처 식별자 (예: hn, reddit_programming, clien)
    language: str        # 'ko' 또는 'en'
    snippet: Optional[str]         # optional: 짧은 본문 요약 또는 부제
    category: Optional[str]        # optional: 태그/카테고리
    created_at: Optional[datetime] # 원본 게시 시각
    collected_at: datetime
    comment_count: int = 0
    upvote_count: int = 0

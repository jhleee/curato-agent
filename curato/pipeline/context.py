from duckduckgo_search import DDGS
from curato.utils.http_client import get_with_delay

class ContextGatherer:

    MAX_BODY_CHARS = 800       # 본문 최대 수집 길이
    MAX_COMMENTS = 5           # 베스트 댓글 최대 수
    MAX_NEWS_RESULTS = 4       # 외부 뉴스 최대 수

    def gather(self, cluster_meta: dict) -> dict:
        """
        클러스터 대표 게시글들로부터 맥락 데이터를 수집합니다.
        """
        context = {
            "body_excerpts": [],
            "top_comments": [],
            "news_headlines": [],
        }

        # 대표 게시글 본문 수집 (최대 2개)
        for url in cluster_meta.get("representative_urls", [])[:2]:
            body = self._fetch_body(url)
            if body:
                context["body_excerpts"].append(body[:self.MAX_BODY_CHARS])

        # 베스트 댓글 수집
        for url in cluster_meta.get("representative_urls", [])[:2]:
            comments = self._fetch_comments(url)
            context["top_comments"].extend(
                comments[:self.MAX_COMMENTS]
            )

        # 외부 뉴스 검색 (이슈 라벨 기반)
        query = cluster_meta.get("final_label") \
             or cluster_meta.get("auto_label", "")
        if query:
            context["news_headlines"] = self._search_news(query)

        return context

    def _fetch_body(self, url: str) -> str:
        try:
            resp = get_with_delay(url, min_delay=1.0, max_delay=2.5)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, 'html.parser')
            # article 또는 main 태그 우선 탐색
            for tag in ['article', 'main', '.post-content', '#content']:
                el = soup.select_one(tag)
                if el:
                    return el.get_text(separator=' ', strip=True)
            return soup.get_text(separator=' ', strip=True)[:self.MAX_BODY_CHARS]
        except Exception:
            return ""

    def _fetch_comments(self, url: str) -> list[str]:
        # 소스별 댓글 수집 로직 (구현은 소스에 따라 분기)
        # 예: HackerNews는 공식 API, Reddit은 JSON API
        return []

    def _search_news(self, query: str) -> list[str]:
        try:
            with DDGS() as ddgs:
                results = ddgs.news(
                    query, max_results=self.MAX_NEWS_RESULTS
                )
            return [r['title'] for r in results]
        except Exception:
            return []

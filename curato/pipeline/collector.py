from typing import Optional
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from curato.core.models import FeedItem
from curato.utils.http_client import get_with_delay
from curato.utils.normalizer import FeedNormalizer
from curato.utils.dup_filter import DuplicateFilter

class BaseCollector:
    """Base class for feed collectors."""
    def __init__(self, db_path: str):
        self.normalizer = FeedNormalizer()
        self.dup_filter = DuplicateFilter(db_path)
        self.skipped_count = 0
    
    def create_feed_item(self, title: str, url: str, source: str, snippet: Optional[str] = None, category: Optional[str] = None, created_at: Optional[datetime] = None) -> Optional[FeedItem]:
        canonical_url = self.normalizer.normalize_url(url)
        url_hash = self.normalizer.compute_url_hash(canonical_url)
        
        if self.dup_filter.is_already_collected(url_hash):
            self.skipped_count += 1
            return None
            
        normalized_title = self.normalizer.normalize_title(title)
        language = self.normalizer.detect_language(normalized_title)
        item_id = url_hash[:16]
        
        return FeedItem(
            id=item_id,
            title=title,
            normalized_title=normalized_title,
            url=url,
            canonical_url=canonical_url,
            url_hash=url_hash,
            source=source,
            language=language,
            snippet=snippet,
            category=category,
            created_at=created_at,
            collected_at=datetime.now(),
        )

class HtmlCollector(BaseCollector):
    """HTML 문서를 파싱하여 피드를 수집하는 콜렉터입니다."""
    def collect_from_html(self, url: str, source_name: str, item_selector: str, title_selector: str, link_selector: str) -> list[FeedItem]:
        items = []
        try:
            resp = get_with_delay(url)
            soup = BeautifulSoup(resp.text, 'html.parser')
            elements = soup.select(item_selector)
            
            for el in elements:
                title_el = el.select_one(title_selector)
                link_el = el.select_one(link_selector)
                
                if title_el and link_el:
                    title = title_el.get_text(strip=True)
                    link = link_el.get('href')
                    
                    if link and link.startswith('/'):
                        # 간단히 base url 결합
                        parsed = urlparse(url)
                        link = f"{parsed.scheme}://{parsed.netloc}{link}"
                    
                    if title and link:
                        item = self.create_feed_item(title=title, url=link, source=source_name)
                        if item:
                            items.append(item)
        except Exception as e:
            print(f"Error collecting from {url}: {e}")
            
        return items

import requests
from curato.core.config import config

class NaverNewsCollector(BaseCollector):
    """네이버 뉴스 API를 사용하여 피드를 수집하는 콜렉터입니다."""
    def __init__(self, db_path: str):
        super().__init__(db_path)
        self.client_id = config.NAVER_CLIENT_ID
        self.client_secret = config.NAVER_CLIENT_SECRET
        self.api_url = "https://openapi.naver.com/v1/search/news.json"

    def collect(self, query: str = "IT 트렌드", display: int = 100) -> list[FeedItem]:
        if not self.client_id or not self.client_secret:
            print("Naver API credentials not found. Skipping Naver News.")
            return []
            
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret
        }
        params = {
            "query": query,
            "display": display,
            "sort": "sim"
        }
        
        items = []
        try:
            resp = requests.get(self.api_url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            for doc in data.get("items", []):
                # 네이버 뉴스는 title과 description에 HTML 태그(<b> 등)가 포함될 수 있음
                raw_title = BeautifulSoup(doc["title"], "html.parser").get_text()
                raw_desc = BeautifulSoup(doc["description"], "html.parser").get_text()
                link = doc["link"] # 원본 링크(originallink) 또는 네이버 뉴스 링크(link)
                
                # datetime parsing (RFC 2822 format)
                pub_date = doc.get("pubDate")
                dt = None
                if pub_date:
                    try:
                        dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
                    except ValueError:
                        pass
                
                item = self.create_feed_item(
                    title=raw_title,
                    url=link,
                    source="naver_news",
                    snippet=raw_desc,
                    category="news",
                    created_at=dt
                )
                if item:
                    items.append(item)
        except Exception as e:
            print(f"Error collecting from Naver API: {e}")
            
        return items

class ClienCollector(HtmlCollector):
    """클리앙 모두의공원 수집기"""
    def collect(self) -> list[FeedItem]:
        url = "https://www.clien.net/service/board/park"
        return self.collect_from_html(
            url=url,
            source_name="clien_park",
            item_selector=".list_item.symph_row",
            title_selector=".list_subject .subject_fixed",
            link_selector=".list_subject"
        )

class RuliwebCollector(HtmlCollector):
    """루리웹 베스트 수집기"""
    def collect(self) -> list[FeedItem]:
        url = "https://bbs.ruliweb.com/best/humor"
        return self.collect_from_html(
            url=url,
            source_name="ruliweb_best",
            item_selector=".table_body:not(.notice)",
            title_selector=".subject .deco",
        )

class NaverIssueCollector(BaseCollector):
    """네이버 뉴스 이슈 페이지를 크롤링하여 본문을 수집하는 콜렉터입니다."""
    def collect(self) -> list[FeedItem]:
        from curato.core.config import config
        urls = config.naver_issue_urls
        if not urls:
            return []
            
        items = []
        for url in urls:
            try:
                resp = get_with_delay(url)
                if not resp:
                    continue
                soup = BeautifulSoup(resp.text, 'html.parser')
                links = soup.select('a[href]')
                article_links = set(l['href'] for l in links if '/article/' in l['href'])
                
                for link in article_links:
                    if len(items) >= 200:
                        break
                    
                    import re
                    match = re.search(r'/article/(\d+)/(\d+)', link)
                    if not match:
                        continue
                    oid, aid = match.groups()
                    print_url = f"https://n.news.naver.com/article/print/{oid}/{aid}"
                    
                    try:
                        p_resp = get_with_delay(print_url)
                        if not p_resp: continue
                        p_soup = BeautifulSoup(p_resp.text, 'html.parser')
                        
                        title_tag = p_soup.select_one('.media_end_head_headline, h3')
                        if not title_tag: continue
                        title = title_tag.text.strip()
                        
                        body_tag = p_soup.select_one('#articeBody, #dic_area')
                        if not body_tag: continue
                        body_text = ' '.join(body_tag.stripped_strings)
                        
                        if len(body_text) < 50: continue
                        
                        item = self.create_feed_item(
                            title=title,
                            url=link,
                            source="Naver Issue",
                            snippet=body_text[:1000]
                        )
                        if item:
                            items.append(item)
                    except Exception as e:
                        print(f"Error fetching print URL {print_url}: {e}")
                        
            except Exception as e:
                print(f"Error fetching issue URL {url}: {e}")
                
        return items

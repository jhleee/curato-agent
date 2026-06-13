import re
import hashlib
import unicodedata
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

class FeedNormalizer:

    # 제거 대상 접두어 패턴
    TITLE_NOISE_PATTERNS = [
        r'^\[속보\]\s*',
        r'^\[단독\]\s*',
        r'^\[펌\]\s*',
        r'^\[공지\]\s*',
        r'^\(사진\)\s*',
        r'^\(영상\)\s*',
        r'^【.*?】\s*',
        r'^◆.*?◆\s*',
        r'\s*\|\s*[가-힣a-zA-Z\s]+$',  # 말미 언론사명 제거 예: | 조선일보
    ]

    # URL 정규화 시 제거할 쿼리 파라미터
    URL_NOISE_PARAMS = [
        'utm_source', 'utm_medium', 'utm_campaign',
        'utm_content', 'utm_term', 'ref', 'from',
        'fbclid', 'gclid', 'mc_cid', 'mc_eid',
    ]

    def normalize_title(self, title: str) -> str:
        # 유니코드 정규화
        title = unicodedata.normalize('NFC', title)
        # 불용 접두어/접미어 제거
        for pattern in self.TITLE_NOISE_PATTERNS:
            title = re.sub(pattern, '', title, flags=re.UNICODE)
        # 이모지 제거
        title = re.sub(
            r'[\U00010000-\U0010ffff\U00002600-\U000027BF]',
            '', title
        )
        # 연속 공백 정리
        title = re.sub(r'\s+', ' ', title).strip()
        return title

    def normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        # 쿼리 파라미터 정제
        params = parse_qs(parsed.query, keep_blank_values=False)
        clean_params = {
            k: v for k, v in params.items()
            if k.lower() not in self.URL_NOISE_PARAMS
        }
        clean_query = urlencode(clean_params, doseq=True)
        # fragment 제거, scheme 소문자 통일
        canonical = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip('/'),
            '', clean_query, ''
        ))
        return canonical

    def compute_url_hash(self, canonical_url: str) -> str:
        return hashlib.sha256(canonical_url.encode()).hexdigest()

    def detect_language(self, text: str) -> str:
        ko_chars = len(re.findall(r'[가-힣]', text))
        total_alpha = len(re.findall(r'[a-zA-Z가-힣]', text))
        if total_alpha == 0:
            return 'unknown'
        return 'ko' if ko_chars / total_alpha > 0.3 else 'en'

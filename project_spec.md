# 프로젝트 기획서 v3: 자율형 로컬 트렌드 클러스터링 에이전트

> **임베딩 우선(Embedding-First), LLM 최소 사용 방식의 로컬 트렌드 탐지·요약·디스코드 퍼블리싱 시스템**

---

## 1. 프로젝트 개요

본 프로젝트는 사용자가 관심 있는 다양한 온라인 커뮤니티 및 뉴스 채널로부터 게시글을 주기적으로 수집하고, 실시간 핵심 이슈를 자동 추출·요약하여 디스코드로 제공하는 자율형 에이전트 스킬입니다.

### 1.1 핵심 구조

```
전체 게시글 수집
    ↓
임베딩 기반 의미 군집화 및 랭킹        ← 비용 0원
    ↓
상위/모호 군집만 LLM 큐레이션          ← 비용 극소
    ↓
최종 이슈만 확장 수집 및 요약          ← 비용 소액
    ↓
디스코드 브리핑 전송
```

기존 방식처럼 제목 전체를 LLM에 일괄 투입하여 이슈를 뽑는 구조에서 벗어나, **임베딩·군집화·정량 랭킹이 1차 탐색 엔진**, **LLM이 후처리 편집 엔진**으로 역할을 분리합니다.

### 1.2 개발 목표 요약

| 목표 | 내용 |
|---|---|
| 비용 | LLM 호출을 최종 선정 이슈 단위로만 제한하여 API 비용 극소화 |
| 정확성 | 정량 지표 기반 랭킹으로 단순 밈/유머글의 상위 선정 방지 |
| 운영성 | SQLite + 로컬 벡터 인덱스로 단일 머신 구동 |
| 개인화 | 임베딩 기반 선호도 반영으로 표현 변형에 강한 추천 |
| 안정성 | Circuit Breaker, Fallback 모드, 비용 상한 제어 |

---

## 2. 핵심 설계 원칙

### 2.1 Embedding-First
전체 제목을 LLM에 넣어 이슈를 찾는 방식은 비용, 일관성, 확장성 모두 약합니다. 본 시스템은 다국어 임베딩 모델로 제목을 벡터화하고, 유사도 기반 군집화와 정량 랭킹으로 이슈 후보를 1차 선별합니다.

### 2.2 LLM-as-Assistant
LLM은 "이슈를 찾는 역할"이 아니라 "이미 선별된 이슈를 정제하고 설명하는 역할"만 담당합니다. 전체 수집 데이터 대비 LLM 입력량을 10% 수준으로 제한하는 것을 목표로 합니다.

### 2.3 Explainable Ranking
이슈 우선순위는 LLM 판단이 아니라 아래 7개 정량 지표의 가중합으로 산정합니다. 결과는 항상 점수와 함께 SQLite에 기록되어 추적 가능합니다.

### 2.4 Local-First
별도의 Vector DB 서버, MQ 인프라 없이 SQLite + FAISS 로컬 파일로 단일 PC/NAS에서 구동합니다.

### 2.5 Late Expansion
수집된 모든 게시글의 본문을 가져오지 않고, 최종 상위 이슈로 선정된 소수에 대해서만 본문/댓글/뉴스를 확장 수집합니다.

---

## 3. 전체 파이프라인

```
[CronJob Trigger]
      │
      ▼
┌─────────────────────┐
│  Stage 1            │
│  Feed Collector     │  수집 / 정규화 / 중복 제거
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 2            │
│  Semantic Indexer   │  임베딩 생성 / 벡터 인덱싱
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 3            │
│  Candidate Grouper  │  Near-Dup Collapse / Topic Clustering
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 4            │
│  Trend Ranker       │  정량 점수 산정 / 상위 이슈 선별
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 5            │
│  LLM Assist Layer   │  모호/저응집 군집만 LLM 큐레이션
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stage 6            │
│  Context Gatherer   │  상위 이슈만 본문/댓글/뉴스 확장 수집
│  & Synthesizer      │  최종 요약 및 디스코드 전송
└─────────────────────┘
```

---

## 4. Stage 1: Feed Collector

### 4.1 역할
다중 소스에서 최신 게시글을 수집하고 최소 메타데이터 중심으로 정규화합니다.

### 4.2 수집 소스 및 방법

| 소스 유형 | 수집 방법 | 비고 |
|---|---|---|
| HackerNews | 공식 Firebase API | `https://hacker-news.firebaseio.com/v0/newstories.json` |
| Reddit | pushshift 또는 Reddit JSON API | `https://reddit.com/r/{sub}/hot.json` |
| 국내 커뮤니티 | RSS 또는 HTML 파싱 | 클리앙, 루리웹, 보배드림 등 |
| 뉴스 | RSS 피드 | 네이버뉴스, IT 전문지 RSS |
| 유튜브 트렌드 | YouTube Data API | optional |

### 4.3 수집 필드 정의

```python
class FeedItem:
    id: str              # URL hash SHA256 앞 16자리
    title: str           # 원본 제목
    normalized_title: str# 정규화 제목
    url: str             # 원본 URL
    canonical_url: str   # 정규화 URL
    url_hash: str        # SHA256(canonical_url)
    source: str          # 출처 식별자 (예: hn, reddit_programming, clien)
    language: str        # 'ko' 또는 'en'
    snippet: str         # optional: 짧은 본문 요약 또는 부제
    category: str        # optional: 태그/카테고리
    created_at: datetime # 원본 게시 시각
    collected_at: datetime
    comment_count: int
    upvote_count: int
```

### 4.4 정규화 로직 구현

```python
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
```

### 4.5 중복 제거 (SQLite 기반)

```python
class DuplicateFilter:

    def __init__(self, db_path: str):
        self.db_path = db_path

    def is_already_collected(self, url_hash: str) -> bool:
        """URL hash 기반 이미 수집된 아이템 여부 확인"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM feed_items WHERE url_hash = ?",
                (url_hash,)
            ).fetchone()
        return row is not None
```

### 4.6 스크래핑 차단 방지

```python
import time
import random
from itertools import cycle

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Safari/605.1.15",

    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
]

ua_cycle = cycle(USER_AGENTS)

def get_with_delay(url: str, min_delay: float = 1.0, max_delay: float = 3.0):
    time.sleep(random.uniform(min_delay, max_delay))
    headers = {"User-Agent": next(ua_cycle)}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response
```

---

## 5. Stage 2: Semantic Indexer

### 5.1 역할
수집된 게시글의 제목과 최소 메타데이터를 다국어 임베딩으로 변환하고 로컬 벡터 인덱스에 저장합니다.

### 5.2 임베딩 입력 포맷 설계

제목만 단독으로 임베딩하면 짧고 모호한 제목의 의미를 제대로 잡지 못합니다. 아래처럼 최소 메타데이터를 함께 구성합니다.

```python
def build_embedding_input(item: FeedItem) -> str:
    """
    임베딩 입력 텍스트를 구성합니다.
    snippet이 있으면 포함하고, 없으면 title + source + category만 사용합니다.
    """
    parts = [f"[title] {item.normalized_title}"]

    if item.source:
        parts.append(f"[source] {item.source}")

    if item.category:
        parts.append(f"[tag] {item.category}")

    if item.snippet:
        # snippet은 200자로 제한
        parts.append(f"[snippet] {item.snippet[:200]}")

    return "\n".join(parts)
```

#### 입력 예시

snippet이 없는 경우:
```text
[title] 결국 발표함
[source] reddit/r/OpenAI
[tag] AI
```

snippet이 있는 경우:
```text
[title] 결국 발표함
[source] reddit/r/OpenAI
[tag] AI
[snippet] OpenAI announced a new API pricing model for o3 and GPT-4o users.
```

### 5.3 임베딩 모델 선정

한국어/영어 혼합 환경을 위해 다음 기준으로 모델을 선정합니다.

| 기준 | 내용 |
|---|---|
| 다국어 지원 | 한국어, 영어 모두 양호한 품질 |
| 로컬 구동 | sentence-transformers 호환 |
| 모델 크기 | 토이 프로젝트 수준에서 CPU/저사양 GPU도 가능 |

**1순위 권장: `BAAI/bge-m3`**  
- 100개 언어 지원
- Dense + Sparse 하이브리드 검색 가능
- 512토큰 제한이 있으나 제목 수준에서는 충분

**2순위: `intfloat/multilingual-e5-small`**  
- 모델 크기 작아 빠름
- 한국어/영어 품질 양호
- 토이 프로젝트에 적합

```python
from sentence_transformers import SentenceTransformer
import numpy as np

class EmbeddingGenerator:
    # 권장 모델 우선순위
    DEFAULT_MODEL = "BAAI/bge-m3"
    FALLBACK_MODEL = "intfloat/multilingual-e5-small"

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name

    def encode(self, texts: list[str]) -> np.ndarray:
        """
        배치 인코딩을 수행합니다.
        bge-m3 사용 시 query prefix 불필요 (passage 모드로 통일)
        """
        embeddings = self.model.encode(
            texts,
            batch_size=64,
            normalize_embeddings=True,  # cosine similarity를 위해 L2 정규화
            show_progress_bar=False
        )
        return embeddings.astype(np.float32)
```

### 5.4 로컬 벡터 인덱스

```python
import faiss
import numpy as np
import os
import pickle

class LocalVectorIndex:
    """
    FAISS 기반 로컬 벡터 인덱스.
    아이템 id와 벡터를 함께 관리합니다.
    """

    def __init__(self, dim: int, index_path: str, id_map_path: str):
        self.dim = dim
        self.index_path = index_path
        self.id_map_path = id_map_path

        if os.path.exists(index_path) and os.path.exists(id_map_path):
            self.index = faiss.read_index(index_path)
            with open(id_map_path, 'rb') as f:
                self.id_map = pickle.load(f)  # {faiss_int_id: item_id}
        else:
            # IndexFlatIP: 내적(Inner Product) 기반
            # normalize_embeddings=True 이면 cosine similarity와 동일
            self.index = faiss.IndexFlatIP(dim)
            self.id_map = {}

        self._next_id = len(self.id_map)

    def add(self, item_id: str, vector: np.ndarray):
        vec = vector.reshape(1, -1).astype(np.float32)
        self.index.add(vec)
        self.id_map[self._next_id] = item_id
        self._next_id += 1

    def search(
        self, query_vector: np.ndarray, top_k: int = 20
    ) -> list[tuple[str, float]]:
        """
        유사도 상위 top_k 아이템 반환.
        반환값: [(item_id, similarity_score), ...]
        """
        vec = query_vector.reshape(1, -1).astype(np.float32)
        scores, indices = self.index.search(vec, top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            item_id = self.id_map.get(idx)
            if item_id:
                results.append((item_id, float(score)))
        return results

    def get_all_vectors(self) -> tuple[list[str], np.ndarray]:
        """
        전체 벡터와 id 목록 반환 (군집화 시 사용)
        """
        n = self.index.ntotal
        if n == 0:
            return [], np.array([])
        vectors = np.zeros((n, self.dim), dtype=np.float32)
        faiss.extract_index_ivf  # not used
        # IndexFlatIP는 reconstruct 지원
        for i in range(n):
            vectors[i] = self.index.reconstruct(i)
        item_ids = [self.id_map[i] for i in range(n)]
        return item_ids, vectors

    def save(self):
        faiss.write_index(self.index, self.index_path)
        with open(self.id_map_path, 'wb') as f:
            pickle.dump(self.id_map, f)
```

---

## 6. Stage 3: Candidate Grouper

### 6.1 역할
벡터 유사도를 활용해 중복 아이템을 먼저 접고, 토픽 군집을 생성합니다.

### 6.2 Stage 3-1: Near-Duplicate Collapse

동일 사건이 여러 제목으로 재게시된 경우를 먼저 하나로 압축합니다.

```python
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

class NearDuplicateCollapser:
    """
    cosine similarity threshold 기반 근접 중복 제거.
    Union-Find 구조로 군집을 만들고,
    각 군집에서 대표 아이템(engagement 가장 높은 것)을 선택합니다.
    """

    SIMILARITY_THRESHOLD = 0.92  # 이 이상이면 같은 이슈로 판단

    def __init__(self, threshold: float = SIMILARITY_THRESHOLD):
        self.threshold = threshold

    def collapse(
        self,
        item_ids: list[str],
        vectors: np.ndarray,
        engagement_scores: dict[str, float]
    ) -> dict[str, list[str]]:
        """
        Returns:
            canonical_id -> [duplicate_ids] 형태의 dict
            canonical_id: engagement 가장 높은 아이템
        """
        n = len(item_ids)
        if n == 0:
            return {}

        # cosine similarity 행렬 계산 (normalize된 벡터면 내적과 동일)
        sim_matrix = cosine_similarity(vectors)

        # Union-Find
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i in range(n):
            for j in range(i + 1, n):
                if sim_matrix[i][j] >= self.threshold:
                    union(i, j)

        # 군집 구성
        groups: dict[int, list[int]] = {}
        for i in range(n):
            root = find(i)
            groups.setdefault(root, []).append(i)

        # 각 군집에서 canonical 아이템 선택 (engagement 최고)
        result = {}
        for root, members in groups.items():
            canonical_idx = max(
                members,
                key=lambda i: engagement_scores.get(item_ids[i], 0)
            )
            canonical_id = item_ids[canonical_idx]
            duplicate_ids = [
                item_ids[i] for i in members if i != canonical_idx
            ]
            result[canonical_id] = duplicate_ids

        return result
```

### 6.3 Stage 3-2: Topic Clustering

중복 정리 후 남은 canonical 아이템들을 토픽 단위로 군집화합니다.

```python
import numpy as np
import hdbscan

class TopicClusterer:
    """
    HDBSCAN 기반 토픽 군집화.
    토픽 수를 미리 지정하지 않아도 되고,
    노이즈(어느 군집에도 속하지 않는 아이템)를 자연스럽게 처리합니다.
    """

    def __init__(
        self,
        min_cluster_size: int = 3,
        min_samples: int = 2,
        metric: str = 'euclidean'
    ):
        """
        min_cluster_size: 최소 군집 크기.
                          수집량이 적으면 2로 낮춰도 됩니다.
        min_samples: 핵심 포인트 판정 기준.
                     낮을수록 더 많이 군집을 만듭니다.
        metric: normalize된 벡터면 'euclidean'도 cosine과 동등합니다.
        """
        self.clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric=metric,
            cluster_selection_method='eom'
        )

    def fit(
        self,
        item_ids: list[str],
        vectors: np.ndarray
    ) -> dict[int, list[str]]:
        """
        Returns:
            cluster_label -> [item_ids] dict
            label -1은 노이즈 (어느 군집에도 속하지 않음)
        """
        if len(item_ids) < 2:
            return {-1: item_ids}

        labels = self.clusterer.fit_predict(vectors)

        clusters: dict[int, list[str]] = {}
        for item_id, label in zip(item_ids, labels):
            clusters.setdefault(int(label), []).append(item_id)

        return clusters

    def compute_centroid(
        self, item_ids: list[str], vectors: np.ndarray, all_item_ids: list[str]
    ) -> np.ndarray:
        """
        주어진 item_ids에 해당하는 벡터들의 평균 (centroid) 계산.
        """
        id_to_idx = {iid: i for i, iid in enumerate(all_item_ids)}
        indices = [id_to_idx[iid] for iid in item_ids if iid in id_to_idx]
        subset = vectors[indices]
        centroid = np.mean(subset, axis=0)
        # 정규화
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        return centroid.astype(np.float32)

    def compute_cohesion(
        self, item_ids: list[str], vectors: np.ndarray,
        all_item_ids: list[str]
    ) -> float:
        """
        군집 응집도: 중심과 각 멤버 간 평균 cosine similarity.
        """
        centroid = self.compute_centroid(item_ids, vectors, all_item_ids)
        id_to_idx = {iid: i for i, iid in enumerate(all_item_ids)}
        indices = [id_to_idx[iid] for iid in item_ids if iid in id_to_idx]
        subset = vectors[indices]
        similarities = subset @ centroid  # L2 정규화된 벡터면 내적 = cosine
        return float(np.mean(similarities))
```

---

## 7. Stage 4: Trend Ranker

### 7.1 역할
각 군집의 trend_score를 계산하고 상위 이슈를 선별합니다.

### 7.2 점수 가중치 기본값

```python
TREND_SCORE_WEIGHTS = {
    'volume':           0.20,
    'engagement':       0.20,
    'burst':            0.25,
    'source_diversity': 0.15,
    'cohesion':         0.10,
    'novelty':          0.05,
    'user_preference':  0.05,
}
```

### 7.3 각 지표 계산 로직

```python
import math
import numpy as np
from datetime import datetime, timedelta

class TrendScoreCalculator:

    def __init__(self, db, weights: dict = None):
        self.db = db
        self.weights = weights or TREND_SCORE_WEIGHTS

    # ── 1) Volume ─────────────────────────────────────────
    def volume_score(self, cluster_size: int, max_size: int) -> float:
        """
        군집 내 게시글 수. log 스케일로 정규화.
        """
        if max_size == 0:
            return 0.0
        return math.log1p(cluster_size) / math.log1p(max_size)

    # ── 2) Engagement ──────────────────────────────────────
    def engagement_score(
        self, total_comments: int, total_upvotes: int,
        max_engagement: float
    ) -> float:
        """
        댓글 수 + 추천 수 합산. log 스케일 정규화.
        """
        raw = total_comments + total_upvotes
        if max_engagement == 0:
            return 0.0
        return math.log1p(raw) / math.log1p(max_engagement)

    # ── 3) Burst ───────────────────────────────────────────
    def burst_score(
        self, recent_count: int, baseline_avg: float
    ) -> float:
        """
        최근 2시간 언급량 / 직전 24시간 시간당 평균 대비 급증도.
        결과를 sigmoid로 [0, 1] 범위로 압축.
        """
        ratio = (recent_count + 1) / (baseline_avg + 1)
        # sigmoid: 1 / (1 + exp(-k*(x-x0)))
        # ratio=1이면 0.5, ratio=4 이상이면 ~0.9
        k = 1.5
        x0 = 2.0
        return 1 / (1 + math.exp(-k * (ratio - x0)))

    # ── 4) Source Diversity ────────────────────────────────
    def source_diversity_score(
        self, source_distribution: dict[str, int]
    ) -> float:
        """
        출처 엔트로피 기반 다양성 점수.
        단일 출처 독점이면 낮고, 여러 출처 고르게 분포하면 높습니다.
        """
        total = sum(source_distribution.values())
        if total == 0:
            return 0.0
        entropy = 0.0
        for count in source_distribution.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        max_entropy = math.log2(len(source_distribution)) if len(source_distribution) > 1 else 1
        return entropy / max_entropy if max_entropy > 0 else 0.0

    # ── 5) Cohesion ────────────────────────────────────────
    def cohesion_score(self, cohesion: float) -> float:
        """
        군집 응집도 그대로 사용. 이미 [0, 1] 범위.
        """
        return max(0.0, min(1.0, cohesion))

    # ── 6) Novelty ─────────────────────────────────────────
    def novelty_score(
        self, cluster_centroid: np.ndarray,
        past_centroids: list[np.ndarray]
    ) -> float:
        """
        과거 24시간 이내 발행된 클러스터들의 중심과의
        최대 유사도를 구한 뒤, 1에서 빼서 새로움 점수로 사용.
        완전히 새로운 이슈면 1.0, 이미 며칠째 반복되는 이슈면 낮아짐.
        """
        if not past_centroids:
            return 1.0
        similarities = [
            float(cluster_centroid @ past_c)
            for past_c in past_centroids
        ]
        max_sim = max(similarities)
        return 1.0 - max_sim

    # ── 7) User Preference ────────────────────────────────
    def user_preference_score(
        self, cluster_centroid: np.ndarray,
        user_interest_centroids: list[tuple[np.ndarray, float]]
    ) -> float:
        """
        사용자 선호 토픽과의 의미적 유사도.
        user_interest_centroids: [(centroid, preference_score), ...]
        preference_score: 양수면 선호, 음수면 비선호.
        """
        if not user_interest_centroids:
            return 0.5  # 선호 데이터 없으면 중립
        weighted_sum = 0.0
        weight_total = 0.0
        for centroid, pref_score in user_interest_centroids:
            sim = float(cluster_centroid @ centroid)
            weighted_sum += sim * pref_score
            weight_total += abs(pref_score)
        if weight_total == 0:
            return 0.5
        # [-1, 1] → [0, 1] 정규화
        raw = weighted_sum / weight_total
        return (raw + 1) / 2

    # ── 최종 점수 계산 ─────────────────────────────────────
    def compute(self, scores: dict[str, float]) -> float:
        total = sum(
            self.weights[key] * scores[key]
            for key in self.weights
        )
        return round(total, 6)
```

### 7.4 상위 이슈 선별 기준

```python
TOP_N_ISSUES = 5          # 최종 선정 이슈 수
MIN_TREND_SCORE = 0.30    # 최소 점수 미달 시 제외
MIN_CLUSTER_SIZE = 2      # 최소 군집 크기
```

---

## 8. Stage 5: LLM Assist Layer

### 8.1 역할
상위 클러스터 중 일부를 LLM으로 큐레이션합니다. LLM은 전체 제목을 받지 않고, 이미 선별된 클러스터의 대표 샘플만 받습니다.

### 8.2 LLM 호출 여부 판정 로직

```python
class LLMAssistGate:
    """
    LLM 호출이 필요한지 판정합니다.
    조건에 해당하지 않으면 자동 라벨링으로 처리합니다.
    """

    COHESION_THRESHOLD = 0.72         # 이 미만이면 LLM 검수
    AUTO_LABEL_MIN_CLUSTER_SIZE = 4   # 이 이상이어야 자동 라벨 신뢰 가능
    CLICKBAIT_KEYWORDS = [
        '이거', '저거', '결국', '드디어', '대박', '헐', '미쳤',
        '충격', '대체', '진짜', '실화', '역대급',
        'this', 'finally', 'wtf', 'omg', 'holy', 'literally'
    ]

    def needs_llm(self, cluster_meta: dict) -> tuple[bool, list[str]]:
        """
        Returns:
            (needs_llm: bool, reasons: list[str])
        """
        reasons = []

        # 1. 응집도 낮음
        if cluster_meta['cohesion'] < self.COHESION_THRESHOLD:
            reasons.append(
                f"low_cohesion:{cluster_meta['cohesion']:.2f}"
            )

        # 2. 군집 크기가 작아 자동 라벨 불신뢰
        if cluster_meta['size'] < self.AUTO_LABEL_MIN_CLUSTER_SIZE:
            reasons.append("small_cluster")

        # 3. 클릭베이트/모호 제목 비율이 높음
        titles = cluster_meta['top_titles']
        clickbait_count = sum(
            1 for t in titles
            if any(kw in t.lower() for kw in self.CLICKBAIT_KEYWORDS)
        )
        if clickbait_count / max(len(titles), 1) > 0.4:
            reasons.append(
                f"clickbait_ratio:{clickbait_count}/{len(titles)}"
            )

        # 4. 자동 라벨의 핵심어 수가 1개 미만
        if len(cluster_meta.get('auto_keywords', [])) < 2:
            reasons.append("insufficient_keywords")

        # 5. 출처가 1개뿐인 고중요도 클러스터
        if (cluster_meta['source_count'] == 1
                and cluster_meta['trend_score'] > 0.60):
            reasons.append("single_source_high_score")

        return len(reasons) > 0, reasons
```

### 8.3 LLM 입력 포맷 최소화

```python
import json

def build_llm_cluster_payload(cluster_meta: dict) -> str:
    """
    LLM에 보낼 최소 데이터 JSON 직렬화.
    원본 제목 전체가 아니라 대표 샘플만 포함합니다.
    """
    payload = {
        "cluster_id": cluster_meta["cluster_id"],
        "top_titles": cluster_meta["top_titles"][:7],   # 최대 7개
        "auto_keywords": cluster_meta["auto_keywords"][:5],
        "source_distribution": cluster_meta["source_distribution"],
        "cohesion": round(cluster_meta["cohesion"], 3),
        "trend_score": round(cluster_meta["trend_score"], 3),
        "ambiguity_reasons": cluster_meta.get("llm_reasons", []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
```

### 8.4 LLM 프롬프트 템플릿

```python
LLM_CLUSTER_LABEL_PROMPT = """
당신은 뉴스·커뮤니티 트렌드 큐레이터입니다.
아래는 온라인 게시글을 의미 기반으로 군집화한 결과의 메타데이터입니다.
주어진 데이터만을 근거로 판단하고, 없는 사실을 추론하거나 창작하지 마십시오.

[군집 데이터]
{cluster_payload}

[사용자 관심 프로필]
선호 키워드: {preferred_keywords}
비선호 키워드: {dispreferred_keywords}

[요청 사항]
아래 JSON 형식으로만 응답하십시오.

{{
  "cluster_id": "{cluster_id}",
  "final_label": "30자 이내의 핵심 이슈 라벨",
  "one_line_summary": "한 문장 요약 (사실 기반)",
  "split_recommendation": false,
  "split_reason": null,
  "content_type": "news | community_discussion | meme | mixed",
  "filter_out": false,
  "filter_reason": null
}}

[판단 기준]
- final_label: 군집이 다루는 핵심 사건/주제를 명확히 표현
- split_recommendation: 군집 내 2개 이상의 독립적 주제가 섞였다면 true
- filter_out: 정치 선동, 혐오, 스팸성 콘텐츠라면 true
- content_type: 주요 콘텐츠 성격 분류
"""
```

### 8.5 비용 비교

| 방식 | 1회 LLM 입력 토큰 | 하루 10회 기준 |
|---|---|---|
| 기존: 제목 200개 전체 | 약 3,000~5,000 token | 약 30,000~50,000 token |
| 개선: 클러스터 대표 샘플 | 약 300~500 token | 약 3,000~5,000 token |

---

## 9. Stage 3-1 보완: 자동 라벨링 (LLM 없이)

LLM 개입 없이도 1차 라벨을 생성합니다.

```python
import re
from collections import Counter

class AutoLabeler:
    """
    군집 내 제목들에서 핵심 명사/엔티티를 추출하여
    LLM 없이도 1차 라벨을 생성합니다.
    """

    # 라벨에서 제외할 불용어
    STOPWORDS_KO = {
        '것', '수', '이', '등', '및', '의', '가', '을', '를',
        '에', '서', '로', '으로', '한', '하는', '있다', '없다',
        '대해', '관해', '위해', '통해', '따라',
    }

    STOPWORDS_EN = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'this', 'that', 'it', 'in', 'on', 'at', 'for', 'with', 'to',
        'of', 'and', 'or', 'but', 'not', 'from',
    }

    def extract_keywords(
        self, titles: list[str], language: str = 'ko', top_n: int = 5
    ) -> list[str]:
        """
        한국어: Kiwi 명사 추출 시도, 없으면 간단한 정규식 폴백
        영어: 대문자 시작 단어(고유명사) 및 빈도 상위 명사 추출
        """
        if language == 'ko':
            return self._extract_ko(titles, top_n)
        else:
            return self._extract_en(titles, top_n)

    def _extract_ko(self, titles: list[str], top_n: int) -> list[str]:
        try:
            from kiwipiepy import Kiwi
            kiwi = Kiwi()
            tokens = []
            for title in titles:
                result = kiwi.analyze(title)
                for sent in result:
                    for token in sent[0]:
                        if token.tag in ('NNG', 'NNP', 'SL') \
                                and len(token.form) >= 2 \
                                and token.form not in self.STOPWORDS_KO:
                            tokens.append(token.form)
        except ImportError:
            # Kiwi 없을 때 폴백: 2글자 이상 한글 명사 형태 추출
            tokens = []
            for title in titles:
                found = re.findall(r'[가-힣]{2,}', title)
                tokens.extend(
                    w for w in found if w not in self.STOPWORDS_KO
                )

        counter = Counter(tokens)
        return [word for word, _ in counter.most_common(top_n)]

    def _extract_en(self, titles: list[str], top_n: int) -> list[str]:
        tokens = []
        for title in titles:
            # 대문자 시작 단어 (고유명사 가능성 높음)
            proper_nouns = re.findall(r'\b[A-Z][a-z]{1,}\b', title)
            tokens.extend(proper_nouns)
            # 소문자 단어 (불용어 제거)
            lower_words = re.findall(r'\b[a-z]{3,}\b', title.lower())
            tokens.extend(
                w for w in lower_words if w not in self.STOPWORDS_EN
            )

        counter = Counter(tokens)
        return [word for word, _ in counter.most_common(top_n)]

    def build_label(self, keywords: list[str]) -> str:
        """
        상위 키워드 최대 3개를 조합해 라벨 생성.
        """
        if not keywords:
            return "미분류 이슈"
        return " · ".join(keywords[:3])
```

---

## 10. Stage 6: Context Gatherer & Synthesizer

### 10.1 역할
최종 선정 이슈에 대해서만 본문, 베스트 댓글, 관련 뉴스를 수집하고 디스코드용 요약을 생성합니다.

### 10.2 확장 수집 로직

```python
from duckduckgo_search import DDGS

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
        for url in cluster_meta["representative_urls"][:2]:
            body = self._fetch_body(url)
            if body:
                context["body_excerpts"].append(body[:self.MAX_BODY_CHARS])

        # 베스트 댓글 수집
        for url in cluster_meta["representative_urls"][:2]:
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
```

### 10.3 최종 요약 프롬프트

```python
LLM_SYNTHESIS_PROMPT = """
당신은 IT·시사 뉴스 에디터입니다.
제공된 텍스트 범위 밖의 사실을 추론하거나 창작하지 마십시오.
사실 영역과 커뮤니티 반응 영역을 반드시 분리하여 작성하십시오.

[이슈 정보]
이슈명: {label}
관련 뉴스 헤드라인:
{news_headlines}

[커뮤니티 반응]
대표 댓글:
{top_comments}

[본문 발췌]
{body_excerpts}

[작성 요청]
아래 JSON 형식으로 작성하십시오.

{{
  "title": "30자 이내 디스코드 표제",
  "facts": "팩트 요약 2~3문장. 뉴스 헤드라인 및 본문 기반.",
  "why_now": "왜 지금 이슈인지 한 문장.",
  "community_reaction": "커뮤니티 반응 요약 1~2문장. 댓글 기반.",
  "links": ["링크1", "링크2"]
}}
"""
```

### 10.4 디스코드 Embed 포맷

```python
import requests as req
from datetime import datetime

class DiscordPublisher:

    REACTION_EMOJIS = ['👍', '👎']

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def publish_brief(self, issues: list[dict], run_id: str):
        """
        상위 이슈 목록을 디스코드 Embed로 전송합니다.
        """
        embeds = []
        for rank, issue in enumerate(issues, start=1):
            embed = {
                "title": f"#{rank} {issue['title']}",
                "description": (
                    f"**📌 팩트**\n{issue['facts']}\n\n"
                    f"**⚡ 왜 지금?**\n{issue['why_now']}\n\n"
                    f"**💬 커뮤니티 반응**\n{issue['community_reaction']}"
                ),
                "color": self._rank_color(rank),
                "fields": [
                    {
                        "name": "🔗 참고 링크",
                        "value": "\n".join(
                            f"[링크 {i+1}]({url})"
                            for i, url in enumerate(issue.get("links", []))
                        ),
                        "inline": False
                    },
                    {
                        "name": "📊 트렌드 점수",
                        "value": str(round(issue.get("trend_score", 0), 2)),
                        "inline": True
                    },
                    {
                        "name": "🏷 출처",
                        "value": " · ".join(issue.get("sources", [])),
                        "inline": True
                    }
                ],
                "footer": {
                    "text": f"run_id: {run_id} | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                }
            }
            embeds.append(embed)

        payload = {
            "content": "**📡 트렌드 브리핑**\n> 👍 좋아요 / 👎 싫어요로 피드백 주세요.",
            "embeds": embeds[:10]  # Discord 최대 10개
        }
        resp = req.post(self.webhook_url, json=payload, timeout=10)
        resp.raise_for_status()

    def _rank_color(self, rank: int) -> int:
        colors = {1: 0xFF4500, 2: 0xFF8C00, 3: 0xFFD700}
        return colors.get(rank, 0x95A5A6)
```

---

## 11. 데이터베이스 설계

### 11.1 테이블 스키마

```sql
-- ─────────────────────────────────────────
-- 수집 게시글 원본
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feed_items (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    normalized_title  TEXT NOT NULL,
    url               TEXT NOT NULL,
    canonical_url     TEXT NOT NULL,
    url_hash          TEXT NOT NULL UNIQUE,
    source            TEXT NOT NULL,
    language          TEXT DEFAULT 'unknown',
    snippet           TEXT,
    category          TEXT,
    created_at        TIMESTAMP,
    collected_at      TIMESTAMP NOT NULL,
    comment_count     INTEGER DEFAULT 0,
    upvote_count      INTEGER DEFAULT 0,
    embedding_stored  INTEGER DEFAULT 0,  -- 1이면 FAISS에 저장 완료
    is_duplicate      INTEGER DEFAULT 0,
    canonical_item_id TEXT,               -- near-dup collapse 후 대표 아이템 id
    FOREIGN KEY (canonical_item_id) REFERENCES feed_items(id)
);

CREATE INDEX IF NOT EXISTS idx_feed_url_hash    ON feed_items(url_hash);
CREATE INDEX IF NOT EXISTS idx_feed_source      ON feed_items(source);
CREATE INDEX IF NOT EXISTS idx_feed_created_at  ON feed_items(created_at);
CREATE INDEX IF NOT EXISTS idx_feed_collected   ON feed_items(collected_at);

-- ─────────────────────────────────────────
-- 클러스터 (이슈 군집)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clusters (
    cluster_id          TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL,
    time_window_start   TIMESTAMP,
    time_window_end     TIMESTAMP,
    centroid_path       TEXT,             -- FAISS 벡터 파일 참조 키
    cohesion            REAL DEFAULT 0,
    volume              INTEGER DEFAULT 0,
    total_comments      INTEGER DEFAULT 0,
    total_upvotes       INTEGER DEFAULT 0,
    burst               REAL DEFAULT 0,
    source_diversity    REAL DEFAULT 0,
    novelty             REAL DEFAULT 0,
    user_preference     REAL DEFAULT 0.5,
    trend_score         REAL DEFAULT 0,
    auto_label          TEXT,
    auto_keywords       TEXT,             -- JSON array
    final_label         TEXT,
    one_line_summary    TEXT,
    content_type        TEXT,             -- news | community_discussion | meme | mixed
    llm_reviewed        INTEGER DEFAULT 0,
    llm_split_flag      INTEGER DEFAULT 0,
    filtered_out        INTEGER DEFAULT 0,
    filter_reason       TEXT,
    status              TEXT DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_cluster_run_id     ON clusters(run_id);
CREATE INDEX IF NOT EXISTS idx_cluster_score      ON clusters(trend_score DESC);
CREATE INDEX IF NOT EXISTS idx_cluster_created_at ON clusters(created_at);

-- ─────────────────────────────────────────
-- 클러스터-아이템 매핑
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cluster_items (
    cluster_id              TEXT NOT NULL,
    item_id                 TEXT NOT NULL,
    similarity_to_centroid  REAL DEFAULT 0,
    is_representative       INTEGER DEFAULT 0,
    PRIMARY KEY (cluster_id, item_id),
    FOREIGN KEY (cluster_id) REFERENCES clusters(cluster_id),
    FOREIGN KEY (item_id) REFERENCES feed_items(id)
);

-- ─────────────────────────────────────────
-- 키워드 선호도 점수
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS keyword_scores (
    keyword     TEXT PRIMARY KEY,
    score       REAL DEFAULT 0,
    updated_at  TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────
-- 사용자 토픽 선호도 프로필 (임베딩 기반)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_topic_profiles (
    topic_id          TEXT PRIMARY KEY,
    centroid_path     TEXT NOT NULL,      -- 로컬 벡터 파일 참조 키
    preference_score  REAL DEFAULT 0,     -- 양수: 선호, 음수: 비선호
    sample_count      INTEGER DEFAULT 0,  -- 피드백 누적 횟수
    updated_at        TIMESTAMP NOT NULL
);

-- ─────────────────────────────────────────
-- 사용자 피드백 로그
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feedback_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id        TEXT NOT NULL,
    discord_message_id TEXT,
    reaction          TEXT NOT NULL,      -- 'like' | 'dislike'
    applied           INTEGER DEFAULT 0,  -- 1이면 프로필에 반영 완료
    created_at        TIMESTAMP NOT NULL,
    FOREIGN KEY (cluster_id) REFERENCES clusters(cluster_id)
);

-- ─────────────────────────────────────────
-- LLM 비용 사용량 로그 (Circuit Breaker용)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS llm_usage_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT,
    stage            TEXT NOT NULL,
    model            TEXT NOT NULL,
    prompt_tokens    INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens     INTEGER DEFAULT 0,
    estimated_cost   REAL DEFAULT 0,      -- USD
    created_at       TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_created_at ON llm_usage_logs(created_at);

-- ─────────────────────────────────────────
-- 파이프라인 실행 로그
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    status          TEXT DEFAULT 'running',  -- running | done | failed | fallback
    items_collected INTEGER DEFAULT 0,
    items_deduplicated INTEGER DEFAULT 0,
    clusters_formed INTEGER DEFAULT 0,
    top_issues_count INTEGER DEFAULT 0,
    llm_calls       INTEGER DEFAULT 0,
    total_cost_usd  REAL DEFAULT 0,
    error_message   TEXT
);
```

---

## 12. 피드백 루프 설계

### 12.1 전체 흐름

```
디스코드 메시지에 👍/👎 반응
    │
    ▼
Discord Webhook Listener (별도 봇 또는 polling)
    │
    ▼
feedback_logs 테이블에 기록
    │
    ▼
FeedbackProcessor.apply()
    ├── keyword_scores 테이블 가중치 업데이트
    └── user_topic_profiles 테이블 센트로이드 선호도 업데이트
    │
    ▼
다음 파이프라인 실행 시
Trend Ranker가 user_preference_score에 반영
```

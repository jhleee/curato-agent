# Curato (자율형 로컬 트렌드 클러스터링 에이전트)

Curato는 사용자가 관심 있는 다양한 온라인 커뮤니티 및 뉴스 채널의 데이터를 수집하여, 임베딩 기반으로 유사한 주제(이슈)들을 군집화하고, LLM을 통해 의미 있는 요약과 라벨을 자동으로 생성하여 디스코드로 발행해주는 자동화 파이프라인입니다.

## 기능 (Features)
- **멀티 소스 수집**: 네이버 뉴스 API, 클리앙, 루리웹 등 다수 채널 동시 크롤링 및 수집
- **로컬 벡터 인덱싱**: `sentence-transformers`를 이용해 문장 임베딩(BGE-m3 등)을 추출하고, `FAISS`를 통해 빠르게 유사도를 계산
- **HDBSCAN 클러스터링**: HDBSCAN 기반 의미론적 문서 군집화를 통해 자연스럽게 트렌드 그룹 형성
- **지표 기반 랭킹 알고리즘**: 볼륨, 반응성(추천/댓글), 최신성(Burst), 출처 다양성 등의 점수를 종합해 핵심 트렌드 산출
- **LLM 큐레이터**: Z.AI / OpenAI 모델과 연동하여 복잡한 이슈에 대해 인사이트가 담긴 제목과 한줄 요약 생성
- **디스코드 퍼블리싱**: 요약된 최종 인사이트를 설정된 디스코드 웹훅으로 자동 발송

## 시스템 요구사항 (Requirements)
- Python 3.10+
- `.env` 파일을 통한 API Key 설정

## 설치 방법 (Installation)
1. 리포지토리 클론 후, 의존성 패키지를 설치합니다.
```bash
pip install -r requirements.txt
```

2. 루트 디렉토리에 `.env` 파일을 생성하고 다음 정보를 입력합니다.
```env
LLM_API_URL="https://api.z.ai/api/paas/v4/chat/completions"
LLM_API_KEY="your_api_key"
LLM_MODEL="glm-4.5-flash"
NAVER_CLIENT_ID="your_naver_id"
NAVER_CLIENT_SECRET="your_naver_secret"
DISCORD_WEBHOOK_URL="your_discord_webhook_url"
DATA_DIR="data"
```

## 사용법 (Usage)
```bash
python -m curato.main
```

## 아키텍처 및 폴더 구조
- `curato/core`: 데이터베이스, 모델(FeedItem), 환경설정(Config) 모음
- `curato/pipeline`: `collector` -> `indexer` -> `grouper` -> `ranker` -> `llm_curator` -> `context` 로 이어지는 프로세스별 모듈
- `curato/utils`: HTTP 요청 지연 처리, 문자열 정규화 등의 공통 유틸리티
- `data/`: SQLite DB 및 FAISS 인덱스 등 영속성 파일이 보관되는 분리된 디렉토리
- `config.yaml`: 랭킹 임계값, 군집 파라미터 등 튜닝이 가능한 외부 설정 파일

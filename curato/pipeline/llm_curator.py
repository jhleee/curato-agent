import os
import json
import requests
from dotenv import load_dotenv

# .env 로드
load_dotenv()

from curato.core.config import config

class LLMAssistGate:
    """
    LLM 호출이 필요한지 판정합니다.
    조건에 해당하지 않으면 자동 라벨링으로 처리합니다.
    """
    def __init__(self):
        self.COHESION_THRESHOLD = config.llm.get("cohesion_threshold", 0.72)
        self.AUTO_LABEL_MIN_CLUSTER_SIZE = config.llm.get("auto_label_min_cluster_size", 4)
        self.CLICKBAIT_KEYWORDS = config.llm.get("clickbait_keywords", [
            '이거', '저거', '결국', '드디어', '대박', '헐', '미쳤',
            '충격', '대체', '진짜', '실화', '역대급',
            'this', 'finally', 'wtf', 'omg', 'holy', 'literally'
        ])

    def needs_llm(self, cluster_meta: dict) -> tuple[bool, list[str]]:
        reasons = []

        # 1. 응집도 낮음
        cohesion = cluster_meta.get('cohesion', 0)
        if cohesion < self.COHESION_THRESHOLD:
            reasons.append(f"low_cohesion:{cohesion:.2f}")

        # 2. 군집 크기가 작아 자동 라벨 불신뢰
        size = cluster_meta.get('size', 0)
        if size < self.AUTO_LABEL_MIN_CLUSTER_SIZE:
            reasons.append("small_cluster")

        # 3. 클릭베이트/모호 제목 비율이 높음
        titles = cluster_meta.get('top_titles', [])
        clickbait_count = sum(
            1 for t in titles
            if any(kw in t.lower() for kw in self.CLICKBAIT_KEYWORDS)
        )
        if titles and clickbait_count / max(len(titles), 1) > 0.4:
            reasons.append(f"clickbait_ratio:{clickbait_count}/{len(titles)}")

        # 4. 자동 라벨의 핵심어 수가 1개 미만
        if len(cluster_meta.get('auto_keywords', [])) < 2:
            reasons.append("insufficient_keywords")

        # 5. 출처가 1개뿐인 고중요도 클러스터
        source_count = cluster_meta.get('source_count', 0)
        trend_score = cluster_meta.get('trend_score', 0)
        if source_count == 1 and trend_score > 0.60:
            reasons.append("single_source_high_score")

        return len(reasons) > 0, reasons


def build_llm_cluster_payload(cluster_meta: dict) -> str:
    """
    LLM에 보낼 최소 데이터 JSON 직렬화.
    원본 제목 전체가 아니라 대표 샘플만 포함합니다.
    """
    payload = {
        "cluster_id": cluster_meta.get("cluster_id"),
        "top_titles": cluster_meta.get("top_titles", [])[:7],   # 최대 7개
        "auto_keywords": cluster_meta.get("auto_keywords", [])[:5],
        "source_distribution": cluster_meta.get("source_distribution", {}),
        "cohesion": round(cluster_meta.get("cohesion", 0), 3),
        "trend_score": round(cluster_meta.get("trend_score", 0), 3),
        "ambiguity_reasons": cluster_meta.get("llm_reasons", []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


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

class LLMCurator:
    def __init__(self):
        self.api_key = config.LLM_API_KEY or config.OPENAI_API_KEY
        self.base_url = config.LLM_API_URL or "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        self.model = config.LLM_MODEL or "glm-4.5-flash"

    def curate_cluster(self, cluster_meta: dict, preferred_keywords: list = None, dispreferred_keywords: list = None) -> dict:
        """
        cluster_meta 정보를 바탕으로 LLM을 호출해 라벨과 요약을 생성합니다.
        """
        payload_str = build_llm_cluster_payload(cluster_meta)
        prompt = LLM_CLUSTER_LABEL_PROMPT.format(
            cluster_payload=payload_str,
            preferred_keywords=", ".join(preferred_keywords or []),
            dispreferred_keywords=", ".join(dispreferred_keywords or []),
            cluster_id=cluster_meta.get("cluster_id", "")
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        data = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            # 일부 API의 경우 response_format 인자를 지원하지 않을 수 있으나
            # 지원하는 모델의 경우 JSON 형태 응답을 강제함
            "response_format": {"type": "json_object"}
        }

        try:
            response = requests.post(self.base_url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Markdown code block 제거 로직
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
                
            return json.loads(content.strip())
        except Exception as e:
            print(f"LLM curation error: {e}")
            return None

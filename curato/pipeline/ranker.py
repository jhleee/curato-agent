import math
import numpy as np

from curato.core.config import config

class TrendScoreCalculator:
    def __init__(self, db=None, weights: dict = None):
        self.db = db
        self.weights = weights or config.ranker.get("trend_score_weights", {
            'volume': 0.20, 'engagement': 0.20, 'burst': 0.25,
            'source_diversity': 0.15, 'cohesion': 0.10,
            'novelty': 0.05, 'user_preference': 0.05
        })
        self.TOP_N_ISSUES = config.ranker.get("top_n_issues", 5)
        self.MIN_TREND_SCORE = config.ranker.get("min_trend_score", 0.30)

    # ── 1) Volume ─────────────────────────────────────────
    def volume_score(self, cluster_size: int, max_size: int) -> float:
        """
        군집 내 게시글 수. log 스케일로 정규화.
        """
        if max_size == 0:
            return 0.0
        return math.log1p(cluster_size) / math.log1p(max_size)

    # ── 2) Engagement ──────────────────────────────────────
    def engagement_score(self, total_comments: int, total_upvotes: int, max_engagement: float) -> float:
        """
        댓글 수 + 추천 수 합산. log 스케일 정규화.
        """
        raw = total_comments + total_upvotes
        if max_engagement == 0:
            return 0.0
        return math.log1p(raw) / math.log1p(max_engagement)

    # ── 3) Burst ───────────────────────────────────────────
    def burst_score(self, recent_count: int, baseline_avg: float) -> float:
        """
        최근 2시간 언급량 / 직전 24시간 시간당 평균 대비 급증도.
        결과를 sigmoid로 [0, 1] 범위로 압축.
        """
        ratio = (recent_count + 1) / (baseline_avg + 1)
        # sigmoid: 1 / (1 + exp(-k*(x-x0)))
        k = 1.5
        x0 = 2.0
        return 1 / (1 + math.exp(-k * (ratio - x0)))

    # ── 4) Source Diversity ────────────────────────────────
    def source_diversity_score(self, source_distribution: dict[str, int]) -> float:
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
    def novelty_score(self, cluster_centroid: np.ndarray, past_centroids: list[np.ndarray]) -> float:
        """
        과거 24시간 이내 발행된 클러스터들의 중심과의
        최대 유사도를 구한 뒤, 1에서 빼서 새로움 점수로 사용.
        """
        if not past_centroids:
            return 1.0
        similarities = [float(cluster_centroid @ past_c) for past_c in past_centroids]
        max_sim = max(similarities)
        return 1.0 - max_sim

    # ── 7) User Preference ────────────────────────────────
    def user_preference_score(self, cluster_centroid: np.ndarray, user_interest_centroids: list[tuple[np.ndarray, float]]) -> float:
        """
        사용자 선호 토픽과의 의미적 유사도.
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
        total = sum(self.weights[key] * scores.get(key, 0.0) for key in self.weights)
        return round(total, 6)

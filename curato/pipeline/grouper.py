import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import hdbscan

from curato.core.config import config

class NearDuplicateCollapser:
    """
    cosine similarity threshold 기반 근접 중복 제거.
    Union-Find 구조로 군집을 만들고,
    각 군집에서 대표 아이템(engagement 가장 높은 것)을 선택합니다.
    """

    def __init__(self, threshold: float = None):
        self.threshold = threshold or config.grouper.get("similarity_threshold", 0.92)

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


class TopicClusterer:
    """
    HDBSCAN 기반 토픽 군집화.
    토픽 수를 미리 지정하지 않아도 되고,
    노이즈(어느 군집에도 속하지 않는 아이템)를 자연스럽게 처리합니다.
    """

    def __init__(
        self,
        min_cluster_size: int = None,
        min_samples: int = None,
        metric: str = 'euclidean'
    ):
        min_cluster_size = min_cluster_size or config.grouper.get("min_cluster_size", 3)
        min_samples = min_samples or config.grouper.get("min_samples", 2)
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

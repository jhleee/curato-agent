import os
import pickle
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

from curato.core.models import FeedItem

def build_embedding_input(item: FeedItem) -> str:
    """
    임베딩 입력 텍스트를 구성합니다.
    snippet이 있으면 포함하고, 없으면 title + source + category만 사용합니다.
    """
    parts = [f"[title] {getattr(item, 'normalized_title', '')}"]

    if hasattr(item, 'source') and item.source:
        parts.append(f"[source] {item.source}")

    if hasattr(item, 'category') and item.category:
        parts.append(f"[tag] {item.category}")

    if hasattr(item, 'snippet') and item.snippet:
        # snippet은 200자로 제한
        parts.append(f"[snippet] {item.snippet[:200]}")

    return "\n".join(parts)

class EmbeddingGenerator:
    # 권장 모델 우선순위
    DEFAULT_MODEL = "BAAI/bge-m3"
    FALLBACK_MODEL = "intfloat/multilingual-e5-small"

    def __init__(self, model_name: str = None):
        if not model_name:
            from curato.core.config import config
            model_name = config.indexer.get("embedding_model", self.DEFAULT_MODEL)
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
        # IndexFlatIP는 reconstruct 지원
        item_ids = [self.id_map[i] for i in range(n)]
        return item_ids, vectors

    def get_vectors_by_ids(self, target_ids: list[str]) -> tuple[list[str], np.ndarray]:
        n = self.index.ntotal
        if n == 0:
            return [], np.array([])
            
        reverse_map = {v: k for k, v in self.id_map.items()}
        found_ids = []
        found_vectors = []
        for tid in target_ids:
            if tid in reverse_map:
                idx = reverse_map[tid]
                found_ids.append(tid)
                found_vectors.append(self.index.reconstruct(idx))
                
        if not found_ids:
            return [], np.array([])
            
        return found_ids, np.array(found_vectors, dtype=np.float32)

    def save(self):
        faiss.write_index(self.index, self.index_path)
        with open(self.id_map_path, 'wb') as f:
            pickle.dump(self.id_map, f)

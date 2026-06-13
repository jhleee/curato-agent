"""
Pipeline runner: core pipeline logic extracted from main.py.
Yields structured status events so both CLI and TUI can consume them.
"""
import os
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from curato.core.database import Database
from curato.core.config import config
from curato.core.models import FeedItem
from curato.pipeline.collector import NaverNewsCollector, ClienCollector, RuliwebCollector
from curato.pipeline.indexer import EmbeddingGenerator, LocalVectorIndex, build_embedding_input
from curato.pipeline.grouper import NearDuplicateCollapser, TopicClusterer
from curato.pipeline.ranker import TrendScoreCalculator
from curato.pipeline.llm_curator import LLMAssistGate, LLMCurator
from curato.pipeline.context import ContextGatherer
from curato.utils.auto_labeler import AutoLabeler
from curato.publishers.discord import DiscordPublisher


@dataclass
class PipelineEvent:
    """A single status event from the pipeline."""
    stage: str          # e.g. "collect", "index", "group", "rank", "llm", "context", "publish"
    status: str         # "start", "progress", "done", "error"
    message: str = ""
    data: dict = field(default_factory=dict)


class PipelineRunner:
    """
    Encapsulates the full curato pipeline.
    Call run() to execute; it yields PipelineEvent objects for progress tracking.
    """

    def __init__(self):
        self.run_id = str(uuid.uuid4())
        self.db = Database(config.DB_PATH)
        self.new_items: list[FeedItem] = []
        self.top_clusters: list[dict] = []
        self.curated_issues: list[dict] = []
        self.final_issues: list[dict] = []

    def run(self):
        """Generator that yields PipelineEvent as each stage progresses."""
        yield from self._stage_init()
        yield from self._stage_collect()

        if not self.new_items:
            yield PipelineEvent("collect", "done", "No new items collected. Pipeline finished early.")
            return

        yield from self._stage_index()
        yield from self._stage_group()
        yield from self._stage_rank()
        yield from self._stage_llm()
        yield from self._stage_context()
        yield from self._stage_publish()

        yield PipelineEvent("pipeline", "done", f"Pipeline run {self.run_id[:8]} completed.",
                            {"run_id": self.run_id, "clusters": len(self.top_clusters),
                             "issues": len(self.final_issues)})

    def run_clustering_only(self, hours: int = 24):
        """Generator that skips collection and runs clustering on recent DB items."""
        yield from self._stage_init()
        
        yield PipelineEvent("collect", "start", f"Fetching items from last {hours} hours...")
        items = self.db.get_recent_items(hours=hours)
        if not items:
            yield PipelineEvent("collect", "done", f"No items found in the last {hours} hours. Aborting.")
            return
            
        self.new_items = items
        yield PipelineEvent("collect", "done", f"Fetched {len(items)} items from DB.", {"total": len(items)})
        
        yield from self._stage_index()
        yield from self._stage_group()
        yield from self._stage_rank()
        yield from self._stage_llm()
        yield from self._stage_context()
        yield from self._stage_publish()
        
        yield PipelineEvent("pipeline", "done", f"Clustering run {self.run_id[:8]} completed.",
                            {"run_id": self.run_id, "clusters": len(self.top_clusters),
                             "issues": len(self.final_issues)})

    # ── Stage implementations ─────────────────────────────────

    def _stage_init(self):
        yield PipelineEvent("init", "start", f"Initializing pipeline run {self.run_id[:8]}...")
        self.db.init_db()
        yield PipelineEvent("init", "done", "Database initialized.")

    def _stage_collect(self):
        yield PipelineEvent("collect", "start", "Starting feed collection...")
        
        collector_flags = config.collectors
        
        all_collectors = [
            ("NaverNews", NaverNewsCollector(config.DB_PATH), collector_flags.get("naver", True)),
            ("Clien", ClienCollector(config.DB_PATH), collector_flags.get("clien", True)),
            ("Ruliweb", RuliwebCollector(config.DB_PATH), collector_flags.get("ruliweb", True)),
        ]

        active_collectors = [(name, coll) for name, coll, is_active in all_collectors if is_active]
        
        if not active_collectors:
            yield PipelineEvent("collect", "done", "All collectors are disabled in config.")
            return

        for name, collector in active_collectors:
            yield PipelineEvent("collect", "progress", f"Collecting from {name}...")
            try:
                items = collector.collect()
                self.new_items.extend(items)
                skipped = getattr(collector, "skipped_count", 0)
                msg = f"{name}: {len(items)} new items (skipped {skipped} duplicates)"
                yield PipelineEvent("collect", "progress", msg,
                                    {"source": name, "count": len(items), "skipped": skipped})
            except Exception as e:
                yield PipelineEvent("collect", "error", f"{name} error: {e}",
                                    {"source": name, "error": str(e)})

        # DB에 저장
        if self.new_items:
            self.db.insert_items(self.new_items)

        yield PipelineEvent("collect", "done",
                            f"Collection complete: {len(self.new_items)} total items.",
                            {"total": len(self.new_items)})

    def _stage_index(self):
        yield PipelineEvent("index", "start", "Loading embedding model...")
        embedder = EmbeddingGenerator()
        dim = config.indexer.get("embedding_dim", 1024)
        index_path = os.path.join(config.DATA_DIR, "vectors.index")
        id_map_path = os.path.join(config.DATA_DIR, "id_map.pkl")
        self._vector_index = LocalVectorIndex(dim=dim, index_path=index_path, id_map_path=id_map_path)

        yield PipelineEvent("index", "progress", f"Encoding {len(self.new_items)} texts...")
        texts = [build_embedding_input(item) for item in self.new_items]
        embeddings = embedder.encode(texts)

        for item, emb in zip(self.new_items, embeddings):
            self._vector_index.add(item.id, emb)
        self._vector_index.save()

        yield PipelineEvent("index", "done",
                            f"Indexed {len(self.new_items)} vectors (dim={dim}).",
                            {"count": len(self.new_items), "dim": dim})

    def _stage_group(self):
        yield PipelineEvent("group", "start", "Grouping candidates...")
        target_ids = [item.id for item in self.new_items]
        all_ids, all_vectors = self._vector_index.get_vectors_by_ids(target_ids)
        
        if not all_ids:
            yield PipelineEvent("group", "done", "No vectors found for grouping.")
            return

        collapser = NearDuplicateCollapser()
        engagement_scores = {item.id: (item.comment_count + item.upvote_count) for item in self.new_items}
        collapsed_groups = collapser.collapse(all_ids, all_vectors, engagement_scores)
        self._collapsed_groups = collapsed_groups

        clusterer = TopicClusterer()
        self._clusterer = clusterer
        canonical_ids = list(collapsed_groups.keys())
        id_to_idx = {iid: i for i, iid in enumerate(all_ids)}
        canonical_vectors = []
        for cid in canonical_ids:
            canonical_vectors.append(all_vectors[id_to_idx[cid]])
        self._canonical_ids = canonical_ids
        self._canonical_vectors = np.array(canonical_vectors) if canonical_vectors else np.empty((0, 1024))

        self._clusters = clusterer.fit(canonical_ids, self._canonical_vectors)

        n_clusters = len([k for k in self._clusters if k != -1])
        noise = len(self._clusters.get(-1, []))
        yield PipelineEvent("group", "done",
                            f"Found {n_clusters} clusters, {noise} noise items.",
                            {"clusters": n_clusters, "noise": noise})

    def _stage_rank(self):
        yield PipelineEvent("rank", "start", "Ranking trends...")
        ranker = TrendScoreCalculator(self.db)
        self.top_clusters = []

        for label, c_item_ids in self._clusters.items():
            if label == -1:
                continue
            
            # 실제 모든 기사(중복 포함) ID 수집
            real_item_ids = []
            for cid in c_item_ids:
                real_item_ids.append(cid)
                real_item_ids.extend(self._collapsed_groups.get(cid, []))
                
            cluster_size = len(real_item_ids)
            if cluster_size < 2:
                continue

            c_items = [item for item in self.new_items if item.id in real_item_ids]
            if not c_items:
                continue

            total_comments = sum(i.comment_count for i in c_items)
            total_upvotes = sum(i.upvote_count for i in c_items)
            burst_baseline = 10

            sources = {}
            for i in c_items:
                sources[i.source] = sources.get(i.source, 0) + 1

            cohesion = self._clusterer.compute_cohesion(
                c_item_ids, self._canonical_vectors, self._canonical_ids)

            scores = {
                'volume': ranker.volume_score(cluster_size, max_size=100),
                'engagement': ranker.engagement_score(total_comments, total_upvotes, max_engagement=1000),
                'burst': ranker.burst_score(cluster_size, baseline_avg=burst_baseline),
                'source_diversity': ranker.source_diversity_score(sources),
                'cohesion': ranker.cohesion_score(cohesion),
                'novelty': 0.5,
                'user_preference': 0.5,
            }

            trend_score = ranker.compute(scores)

            cluster_info = {
                'cluster_id': f"cluster_{label}_{self.run_id[:8]}",
                'top_titles': [i.title for i in c_items[:5]],
                'items': c_items,
                'trend_score': trend_score,
                'size': cluster_size,
                'cohesion': cohesion,
                'sources': sources,
                'scores': scores,
            }
            self.top_clusters.append(cluster_info)

        self.top_clusters.sort(key=lambda x: x['trend_score'], reverse=True)
        self.top_clusters = self.top_clusters[:ranker.TOP_N_ISSUES]

        yield PipelineEvent("rank", "done",
                            f"Selected top {len(self.top_clusters)} clusters.",
                            {"count": len(self.top_clusters)})

    def _stage_llm(self):
        yield PipelineEvent("llm", "start", "LLM curation starting...")
        llm_gate = LLMAssistGate()
        llm_curator = LLMCurator()
        auto_labeler = AutoLabeler()
        self.curated_issues = []

        for cluster in self.top_clusters:
            needs_llm, reasons = llm_gate.needs_llm(cluster)
            if needs_llm:
                yield PipelineEvent("llm", "progress",
                                    f"LLM curating {cluster['cluster_id']}",
                                    {"method": "llm", "reasons": reasons})
                llm_res = llm_curator.curate_cluster(cluster)
                if llm_res:
                    cluster.update(llm_res)
            else:
                yield PipelineEvent("llm", "progress",
                                    f"Auto-labeling {cluster['cluster_id']}",
                                    {"method": "auto"})
                labels = auto_labeler.extract_keywords(cluster['top_titles'])
                cluster['final_label'] = auto_labeler.build_label(labels)
                
            self.curated_issues.append(cluster)

        yield PipelineEvent("llm", "done",
                            f"Curated {len(self.curated_issues)} issues.",
                            {"count": len(self.curated_issues)})

    def _stage_context(self):
        yield PipelineEvent("context", "start", "Gathering context...")
        gatherer = ContextGatherer()
        self.final_issues = []

        for issue in self.curated_issues:
            context = gatherer.gather(issue)
            issue.update(context)
            self.final_issues.append(issue)

        yield PipelineEvent("context", "done",
                            f"Context gathered for {len(self.final_issues)} issues.")

    def _stage_publish(self):
        yield PipelineEvent("publish", "start", "Publishing results...")
        webhook_url = config.DISCORD_WEBHOOK_URL
        publisher = DiscordPublisher(webhook_url=webhook_url)
        if publisher.webhook_url:
            publisher.publish_brief(self.final_issues, self.run_id)
            yield PipelineEvent("publish", "done", "Published to Discord.")
        else:
            yield PipelineEvent("publish", "done", "No webhook configured. Skipped Discord publish.")

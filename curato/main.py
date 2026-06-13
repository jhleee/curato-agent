import os
import uuid
from datetime import datetime

# Import core
from curato.core.database import Database
from curato.core.config import config
from curato.core.models import FeedItem

# Import pipeline components
from curato.pipeline.collector import NaverNewsCollector, ClienCollector, RuliwebCollector
from curato.pipeline.indexer import EmbeddingGenerator, LocalVectorIndex, build_embedding_input
from curato.pipeline.grouper import NearDuplicateCollapser, TopicClusterer
from curato.pipeline.ranker import TrendScoreCalculator
from curato.pipeline.llm_curator import LLMAssistGate, LLMCurator
from curato.pipeline.context import ContextGatherer
from curato.utils.auto_labeler import AutoLabeler

# Import publisher
from curato.publishers.discord import DiscordPublisher

def main():
    # 1. Initialize Pipeline context
    run_id = str(uuid.uuid4())
    print(f"Starting pipeline run: {run_id}")
    
    db_path = config.DB_PATH
    db = Database(db_path)
    db.init_db()

    # 2. Stage 1: Feed Collector
    print("Stage 1: Collecting feeds...")
    collectors = [
        NaverNewsCollector(db_path),
        ClienCollector(db_path),
        RuliwebCollector(db_path)
    ]
    
    new_items = []
    for collector in collectors:
        items = collector.collect()
        new_items.extend(items)
        print(f"Collected {len(items)} items from {collector.__class__.__name__}")
    
    if not new_items:
        print("No new items to process. Exiting.")
        return

    # 3. Stage 2: Semantic Indexer
    print("Stage 2: Semantic Indexing...")
    embedder = EmbeddingGenerator()
    dim = config.indexer.get("embedding_dim", 1024)
    index_path = os.path.join(config.DATA_DIR, "vectors.index")
    id_map_path = os.path.join(config.DATA_DIR, "id_map.pkl")
    vector_index = LocalVectorIndex(dim=dim, index_path=index_path, id_map_path=id_map_path)
    
    texts_to_encode = [build_embedding_input(item) for item in new_items]
    embeddings = embedder.encode(texts_to_encode)
    
    for item, emb in zip(new_items, embeddings):
        vector_index.add(item.id, emb)
    vector_index.save()

    # 4. Stage 3: Candidate Grouper
    print("Stage 3: Grouping Candidates...")
    all_ids, all_vectors = vector_index.get_all_vectors()
    
    collapser = NearDuplicateCollapser()
    engagement_scores = {item.id: (item.comment_count + item.upvote_count) for item in new_items}
    collapsed_groups = collapser.collapse(all_ids, all_vectors, engagement_scores)
    
    clusterer = TopicClusterer()
    canonical_ids = list(collapsed_groups.keys())
    # we need subset of vectors for canonical_ids
    canonical_vectors = []
    id_to_idx = {iid: i for i, iid in enumerate(all_ids)}
    for cid in canonical_ids:
        canonical_vectors.append(all_vectors[id_to_idx[cid]])
    import numpy as np
    canonical_vectors = np.array(canonical_vectors) if canonical_vectors else np.empty((0, 1024))
    
    clusters = clusterer.fit(canonical_ids, canonical_vectors)

    # 5. Stage 4: Trend Ranker
    print("Stage 4: Ranking Trends...")
    ranker = TrendScoreCalculator(db)
    top_clusters = []
    
    for label, c_item_ids in clusters.items():
        if label == -1: # skip noise
            continue
            
        cluster_size = len(c_item_ids)
        if cluster_size < 2:
            continue
            
        # extract items for this cluster
        c_items = [item for item in new_items if item.id in c_item_ids]
        if not c_items:
            continue
            
        total_comments = sum(i.comment_count for i in c_items)
        total_upvotes = sum(i.upvote_count for i in c_items)
        
        # calculate dummy baseline for burst (in real use, query DB)
        burst_baseline = 10 
        
        sources = {}
        for i in c_items:
            sources[i.source] = sources.get(i.source, 0) + 1
            
        cohesion = clusterer.compute_cohesion(c_item_ids, canonical_vectors, canonical_ids)
        
        scores = {
            'volume': ranker.volume_score(cluster_size, max_size=100),
            'engagement': ranker.engagement_score(total_comments, total_upvotes, max_engagement=1000),
            'burst': ranker.burst_score(cluster_size, baseline_avg=burst_baseline),
            'source_diversity': ranker.source_diversity_score(sources),
            'cohesion': ranker.cohesion_score(cohesion),
            'novelty': 0.5, # placeholder
            'user_preference': 0.5 # placeholder
        }
        
        trend_score = ranker.compute(scores)
        
        cluster_info = {
            'cluster_id': f"cluster_{label}_{run_id[:8]}",
            'top_titles': [i.title for i in c_items[:5]], # first 5 titles
            'items': c_items,
            'trend_score': trend_score,
            'size': cluster_size,
            'cohesion': cohesion
        }
        top_clusters.append(cluster_info)

    top_clusters.sort(key=lambda x: x['trend_score'], reverse=True)
    top_clusters = top_clusters[:5] # Top 5 issues
    print(f"Selected Top {len(top_clusters)} Clusters.")

    # 6. Stage 5: LLM Assist Layer
    print("Stage 5: LLM Assisting...")
    llm_gate = LLMAssistGate()
    llm_curator = LLMCurator()
    auto_labeler = AutoLabeler()

    curated_issues = []
    for cluster in top_clusters:
        needs_llm, reasons = llm_gate.needs_llm(cluster)
        if needs_llm:
            print(f"LLM used for cluster {cluster['cluster_id']} (Reason: {reasons})")
            curated_issue = llm_curator.curate_cluster(cluster)
        else:
            print(f"Auto Labeler used for cluster {cluster['cluster_id']}")
            labels = auto_labeler.extract_keywords(cluster['top_titles'])
            cluster['final_label'] = auto_labeler.build_label(labels)
            curated_issue = cluster
        curated_issues.append(curated_issue)

    # 7. Stage 6: Context Gathering & Publishing
    print("Stage 6: Context Gathering and Discord Publishing...")
    gatherer = ContextGatherer()
    final_issues_to_publish = []
    
    for issue in curated_issues:
        context = gatherer.gather(issue)
        issue.update(context)
        final_issues_to_publish.append(issue)

    webhook_url = config.DISCORD_WEBHOOK_URL
    publisher = DiscordPublisher(webhook_url=webhook_url)
    if publisher.webhook_url:
        publisher.publish_brief(final_issues_to_publish, run_id)
    else:
        print("No DISCORD_WEBHOOK_URL provided. Skipping publish.")

    print(f"Pipeline run {run_id} completed.")

if __name__ == "__main__":
    main()

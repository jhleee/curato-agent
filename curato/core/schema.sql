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

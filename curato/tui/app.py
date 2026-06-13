"""
Curato TUI — Terminal User Interface for the trend curation pipeline.
Built with Textual framework.

Tabs:
  1. 대시보드  — Pipeline execution, stage progress, live log
  2. 수집      — Per-source manual collection, collection stats
  3. 결과      — Cluster results table + detail drill-down
  4. 설정      — View/edit config.yaml parameters live
  5. DB 탐색   — Browse collected feed_items from SQLite
"""
import os
import yaml
import sqlite3
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, Static, Label, Button, Switch, Input,
    DataTable, RichLog, Select, Rule,
    TabbedContent, TabPane, Collapsible,
)
from textual.reactive import reactive
from textual.message import Message

from curato.core.config import config
from curato.core.database import Database
from curato.pipeline.runner import PipelineRunner, PipelineEvent


# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

STAGE_ICONS = {
    "init": "⚙️", "collect": "📡", "index": "🧠", "group": "🔗",
    "rank": "📊", "llm": "🤖", "context": "🔍", "publish": "📢",
    "pipeline": "✅",
}
STAGE_NAMES = {
    "init": "초기화", "collect": "데이터 수집", "index": "임베딩 인덱싱",
    "group": "후보 군집화", "rank": "트렌드 랭킹", "llm": "LLM 큐레이션",
    "context": "컨텍스트 확장", "publish": "퍼블리싱", "pipeline": "파이프라인",
}

COLLECTOR_INFO = [
    {"key": "naver", "name": "네이버 뉴스", "icon": "📰", "cls_name": "NaverNewsCollector"},
    {"key": "clien", "name": "클리앙", "icon": "💬", "cls_name": "ClienCollector"},
    {"key": "ruliweb", "name": "루리웹", "icon": "🎮", "cls_name": "RuliwebCollector"},
]


# ═══════════════════════════════════════════════════════════════
#  Widget: Stage Cards (Dashboard)
# ═══════════════════════════════════════════════════════════════

class StageCard(Static):
    """A small card showing the status of one pipeline stage."""

    def __init__(self, stage_key: str, **kwargs):
        super().__init__(**kwargs)
        self.stage_key = stage_key
        self.icon = STAGE_ICONS.get(stage_key, "⏳")
        self.stage_label = STAGE_NAMES.get(stage_key, stage_key)

    def compose(self) -> ComposeResult:
        yield Label(f"{self.icon} {self.stage_label}", id=f"stage-label-{self.stage_key}")
        yield Label("⏳ 대기중", id=f"stage-status-{self.stage_key}")

    def update_status(self, status: str, message: str = ""):
        status_label = self.query_one(f"#stage-status-{self.stage_key}", Label)
        short = (message[:36] + "…") if message and len(message) > 36 else (message or "")
        if status == "start":
            status_label.update("🔄 진행중...")
            self.add_class("running"); self.remove_class("done", "error")
        elif status == "done":
            status_label.update(f"✅ {short or '완료'}")
            self.add_class("done"); self.remove_class("running", "error")
        elif status == "error":
            status_label.update(f"❌ {short or '오류'}")
            self.add_class("error"); self.remove_class("running")
        elif status == "progress":
            status_label.update(f"🔄 {short or '...'}")

    def reset(self):
        s = self.query_one(f"#stage-status-{self.stage_key}", Label)
        s.update("⏳ 대기중")
        self.remove_class("running", "done", "error")


# ═══════════════════════════════════════════════════════════════
#  Widget: Source Card (수집 탭)
# ═══════════════════════════════════════════════════════════════

class SourceCard(Static):
    """Card for an individual data source with collect button."""

    class CollectRequested(Message):
        def __init__(self, source_key: str):
            super().__init__()
            self.source_key = source_key

    def __init__(self, info: dict, **kwargs):
        super().__init__(**kwargs)
        self.source_key = info["key"]
        self.source_name = info["name"]
        self.source_icon = info["icon"]
        self.cls_name = info["cls_name"]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="source-header"):
            yield Label(f"{self.source_icon} {self.source_name}", classes="source-name")
            yield Button("수집", id=f"btn-collect-{self.source_key}",
                         variant="primary", classes="source-btn")
        yield Label("대기중", id=f"source-status-{self.source_key}", classes="source-status")
        yield Label("", id=f"source-count-{self.source_key}", classes="source-count")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == f"btn-collect-{self.source_key}":
            self.post_message(self.CollectRequested(self.source_key))

    def set_status(self, text: str, css_class: str = ""):
        lbl = self.query_one(f"#source-status-{self.source_key}", Label)
        lbl.update(text)
        self.remove_class("src-running", "src-done", "src-error")
        if css_class:
            self.add_class(css_class)

    def set_count(self, text: str):
        lbl = self.query_one(f"#source-count-{self.source_key}", Label)
        lbl.update(text)


# ═══════════════════════════════════════════════════════════════
#  Widget: Config Editor (설정 탭)
# ═══════════════════════════════════════════════════════════════

class ConfigRow(Static):
    """A single config key-value row with an editable input."""

    class ValueChanged(Message):
        def __init__(self, section: str, key: str, value: str):
            super().__init__()
            self.section = section
            self.key = key
            self.value = value

    def __init__(self, section: str, key: str, value, **kwargs):
        super().__init__(**kwargs)
        self.section = section
        self.cfg_key = key
        self.cfg_value = value

    def compose(self) -> ComposeResult:
        display_val = str(self.cfg_value)
        with Horizontal(classes="config-row"):
            yield Label(f"{self.section}.{self.cfg_key}", classes="config-key")
            yield Input(value=display_val,
                        id=f"cfg-input-{self.section}-{self.cfg_key}",
                        classes="config-input")

    def on_input_submitted(self, event: Input.Submitted):
        self.post_message(self.ValueChanged(self.section, self.cfg_key, event.value))


# ═══════════════════════════════════════════════════════════════
#  Widget: Results Table + Detail (결과 탭)
# ═══════════════════════════════════════════════════════════════

class ResultsTable(Static):
    def compose(self) -> ComposeResult:
        table = DataTable(id="results-table")
        table.cursor_type = "row"
        yield table

    def on_mount(self):
        table = self.query_one("#results-table", DataTable)
        table.add_columns("순위", "라벨", "점수", "크기", "응집도", "출처")

    def populate(self, clusters: list[dict]):
        table = self.query_one("#results-table", DataTable)
        table.clear()
        for rank, c in enumerate(clusters, 1):
            label = c.get("final_label") or (c.get("top_titles", [""])[0][:30])
            score = f"{c.get('trend_score', 0):.4f}"
            size = str(c.get("size", 0))
            cohesion = f"{c.get('cohesion', 0):.3f}"
            sources_dict = c.get("sources", {})
            sources_str = ", ".join(sources_dict.keys()) if isinstance(sources_dict, dict) else str(sources_dict)
            table.add_row(str(rank), label, score, size, cohesion, sources_str)


class ClusterDetail(Static):
    def compose(self) -> ComposeResult:
        yield Label("[dim]클러스터를 선택하세요[/dim]", id="detail-label")
        yield Rule()
        detail_table = DataTable(id="detail-table")
        detail_table.cursor_type = "row"
        yield detail_table

    def on_mount(self):
        table = self.query_one("#detail-table", DataTable)
        table.add_columns("제목", "출처", "URL")

    def show_cluster(self, cluster: dict):
        label = self.query_one("#detail-label", Label)
        cid = cluster.get("cluster_id", "?")
        final = cluster.get("final_label", "")
        summary = cluster.get("one_line_summary", "")
        text = f"[bold]{cid}[/bold]"
        if final:
            text += f"  ─  {final}"
        if summary:
            text += f"\n{summary}"
        label.update(text)

        table = self.query_one("#detail-table", DataTable)
        table.clear()
        for item in cluster.get("items", []):
            title = item.title[:50] if hasattr(item, "title") else str(item)[:50]
            source = item.source if hasattr(item, "source") else ""
            url = item.url[:60] if hasattr(item, "url") else ""
            table.add_row(title, source, url)


# ═══════════════════════════════════════════════════════════════
#  Widget: Cluster Browser (저장된 클러스터 조회)
# ═══════════════════════════════════════════════════════════════

class ClusterBrowser(Static):
    def compose(self) -> ComposeResult:
        with Horizontal():
            table = DataTable(id="cluster-list-table")
            table.cursor_type = "row"
            yield table

            with Vertical(id="cluster-browser-right"):
                yield Label("선택된 클러스터 상세", id="cb-detail-label", classes="section-title")
                item_table = DataTable(id="cb-item-table")
                item_table.cursor_type = "row"
                yield item_table

    def on_mount(self):
        c_table = self.query_one("#cluster-list-table", DataTable)
        c_table.add_columns("생성일시", "라벨/요약", "점수", "크기", "응집도")
        
        i_table = self.query_one("#cb-item-table", DataTable)
        i_table.add_columns("작성일", "제목", "출처", "URL")

    def populate_clusters(self, clusters: list[dict]):
        table = self.query_one("#cluster-list-table", DataTable)
        table.clear()
        self._clusters_data = clusters
        for i, c in enumerate(clusters):
            dt = str(c.get("created_at", ""))[:16]
            label = c.get("final_label") or c.get("one_line_summary") or "알 수 없음"
            score = f"{c.get('trend_score', 0):.4f}"
            size = str(c.get("volume", 0))
            cohesion = f"{c.get('cohesion', 0):.3f}"
            table.add_row(dt, label[:30], score, size, cohesion, key=str(i))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        if event.data_table.id == "cluster-list-table":
            if not hasattr(self, "_clusters_data"):
                return
            idx = int(event.row_key.value)
            cluster = self._clusters_data[idx]
            self._show_cluster_items(cluster)

    def _show_cluster_items(self, cluster: dict):
        label = self.query_one("#cb-detail-label", Label)
        cid = cluster.get("cluster_id", "?")
        final = cluster.get("final_label", "")
        summary = cluster.get("one_line_summary", "")
        text = f"[bold]{cid}[/bold]\n"
        if final: text += f"라벨: {final}\n"
        if summary: text += f"요약: {summary}"
        label.update(text)

        try:
            from curato.core.database import Database
            from curato.core.config import config
            db = Database(config.DB_PATH)
            items = db.get_cluster_items(cid)
            
            table = self.query_one("#cb-item-table", DataTable)
            table.clear()
            for item in items:
                dt = str(item.get("created_at", ""))[:16]
                title = item.get("title", "")[:50]
                source = item.get("source", "")
                url = item.get("url", "")[:40]
                table.add_row(dt, title, source, url)
        except Exception as e:
            label.update(f"[red]Failed to load items: {e}[/red]")


# ═══════════════════════════════════════════════════════════════
#  Main App
# ═══════════════════════════════════════════════════════════════

class CuratoApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "Curato — 트렌드 큐레이터"
    SUB_TITLE = "자율형 로컬 트렌드 클러스터링 에이전트"

    BINDINGS = [
        Binding("r", "run_pipeline", "파이프라인 실행", show=True),
        Binding("q", "quit", "종료", show=True),
        Binding("d", "toggle_dark", "다크모드 전환", show=True),
        Binding("f5", "refresh_db", "DB 새로고침", show=True),
    ]

    is_running = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._runner: PipelineRunner | None = None
        self._clusters: list[dict] = []

    # ── Layout ────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="dashboard"):

            # ── Tab 1: 대시보드 ──
            with TabPane("대시보드", id="dashboard"):
                with Vertical(id="dashboard-layout"):
                    with Horizontal(id="top-bar"):
                        yield Button("▶ 전체 파이프라인 실행", id="btn-run", variant="success")
                        yield Button("🧠 DB 데이터로 클러스터링", id="btn-run-cluster", variant="primary")
                        yield Button("■ 중지", id="btn-stop", variant="error", disabled=True)
                        yield Label("   준비됨", id="status-text")
                    with Horizontal(id="stage-panel"):
                        stages = ["init", "collect", "index", "group",
                                  "rank", "llm", "context", "publish"]
                        for s in stages:
                            yield StageCard(s, id=f"card-{s}", classes="stage-card")
                    yield RichLog(id="log", highlight=True, markup=True, wrap=True,
                                  min_width=40)

            # ── Tab 2: 수집 ──
            with TabPane("수집", id="collect-tab"):
                with Vertical(id="collect-layout"):
                    with Horizontal(id="collect-top-bar"):
                        yield Button("전체 수집", id="btn-collect-all", variant="success")
                        yield Label("   개별 소스를 선택하여 수동 수집할 수 있습니다.", id="collect-desc")
                    with Horizontal(id="source-cards"):
                        for info in COLLECTOR_INFO:
                            yield SourceCard(info, id=f"srccard-{info['key']}",
                                             classes="source-card")
                    yield Label("수집 로그", classes="section-label")
                    yield RichLog(id="collect-log", highlight=True, markup=True,
                                  wrap=True, min_width=40)

            # ── Tab 3: 결과 ──
            with TabPane("결과", id="results"):
                with Horizontal(id="results-layout"):
                    yield ResultsTable(id="results-panel")
                    yield ClusterDetail(id="detail-panel")

            # ── Tab 4: 설정 ──
            with TabPane("설정", id="config-tab"):
                with Vertical(id="config-layout"):
                    with Horizontal(id="config-top-bar"):
                        yield Button("💾 저장", id="btn-config-save", variant="success")
                        yield Button("↺ 되돌리기", id="btn-config-reload", variant="warning")
                        yield Label("   config.yaml 값을 수정한 뒤 저장하세요.", id="config-desc")
                    with VerticalScroll(id="config-scroll"):
                        yield Static(id="config-fields-container")

            # ── Tab 5: DB 탐색 ──
            with TabPane("DB 탐색", id="db-tab"):
                with Vertical(id="db-layout"):
                    with Horizontal(id="db-top-bar"):
                        yield Button("새로고침", id="btn-db-refresh", variant="primary")
                        yield Input(placeholder="검색어 입력 (제목 필터)",
                                    id="db-search-input", classes="db-search")
                        yield Label("", id="db-count-label")
                    db_table = DataTable(id="db-table")
                    db_table.cursor_type = "row"
                    yield db_table

            # ── Tab 6: 클러스터 이력 ──
            with TabPane("클러스터 이력", id="cluster-history-tab"):
                yield ClusterBrowser(id="cluster-browser-panel")

        yield Footer()

    # ── Mount ─────────────────────────────────────────────────

    def on_mount(self):
        # Setup DB table columns
        db_table = self.query_one("#db-table", DataTable)
        db_table.add_columns("ID", "제목", "출처", "수집일시", "URL")

        # Load config fields
        self._load_config_fields()

        # Load DB data
        self._refresh_db_table()

    # ═══════════════════════════════════════════════════════════
    #  Actions
    # ═══════════════════════════════════════════════════════════

    def action_run_pipeline(self):
        if not self.is_running:
            self._start_pipeline()

    def action_toggle_dark(self):
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def action_refresh_db(self):
        self._refresh_db_table()

    # ═══════════════════════════════════════════════════════════
    #  Button Handlers
    # ═══════════════════════════════════════════════════════════

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-run":
            self._start_pipeline(clustering_only=False)
        elif bid == "btn-run-cluster":
            self._start_pipeline(clustering_only=True)
        elif bid == "btn-stop":
            self._stop_pipeline()
        elif bid == "btn-collect-all":
            self._collect_all_sources()
        elif bid == "btn-config-save":
            self._save_config()
        elif bid == "btn-config-reload":
            self._load_config_fields()
            self._show_notify("설정이 원본에서 다시 로드되었습니다.")
        elif bid == "btn-db-refresh":
            self._refresh_db_table()

    # ── DataTable row selection ───────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table.id == "results-table":
            row_idx = event.cursor_row
            if 0 <= row_idx < len(self._clusters):
                detail = self.query_one("#detail-panel", ClusterDetail)
                detail.show_cluster(self._clusters[row_idx])

    # ── Input handlers ────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "db-search-input":
            self._refresh_db_table(event.value)

    # ── SourceCard message handler ────────────────────────────

    def on_source_card_collect_requested(self, event: SourceCard.CollectRequested):
        self._collect_single_source(event.source_key)

    # ═══════════════════════════════════════════════════════════
    #  Pipeline Execution (대시보드)
    # ═══════════════════════════════════════════════════════════

    def _start_pipeline(self, clustering_only=False):
        if self.is_running:
            return
        self.is_running = True

        self.query_one("#btn-run", Button).disabled = True
        self.query_one("#btn-run-cluster", Button).disabled = True
        self.query_one("#btn-stop", Button).disabled = False
        
        mode_text = "클러스터링" if clustering_only else "파이프라인"
        self.query_one("#status-text", Label).update(f"   🔄 {mode_text} 실행 중...")

        log = self.query_one("#log", RichLog)
        log.clear()
        log.write(f"[bold cyan]━━━ {mode_text} 시작 ━━━[/bold cyan]")

        for s in ["init", "collect", "index", "group", "rank", "llm", "context", "publish"]:
            self.query_one(f"#card-{s}", StageCard).reset()

        self.run_worker(lambda: self._run_pipeline_worker(clustering_only), thread=True)

    def _stop_pipeline(self):
        self.is_running = False
        self.query_one("#status-text", Label).update("   ⏹ 중지됨")

    def _run_pipeline_worker(self, clustering_only=False):
        runner = PipelineRunner()
        self._runner = runner
        
        generator = runner.run_clustering_only() if clustering_only else runner.run()
        
        for event in generator:
            if not self.is_running:
                self.call_from_thread(self._on_pipeline_event,
                                      PipelineEvent("pipeline", "done", "사용자에 의해 중지됨."))
                return
            self.call_from_thread(self._on_pipeline_event, event)
        self.call_from_thread(self._on_pipeline_complete, runner)

    def _on_pipeline_event(self, event: PipelineEvent):
        log = self.query_one("#log", RichLog)
        icon = STAGE_ICONS.get(event.stage, "⏳")
        if event.status == "start":
            log.write(f"\n[bold yellow]{icon} {STAGE_NAMES.get(event.stage, event.stage)}[/bold yellow]")
        elif event.status == "progress":
            log.write(f"  [dim]{event.message}[/dim]")
        elif event.status == "done":
            log.write(f"  [green]✅ {event.message}[/green]")
        elif event.status == "error":
            log.write(f"  [red]❌ {event.message}[/red]")

        try:
            self.query_one(f"#card-{event.stage}", StageCard).update_status(
                event.status, event.message)
        except Exception:
            pass

    def _on_pipeline_complete(self, runner: PipelineRunner):
        self.is_running = False
        self.query_one("#btn-run", Button).disabled = False
        self.query_one("#btn-run-cluster", Button).disabled = False
        self.query_one("#btn-stop", Button).disabled = True
        self.query_one("#status-text", Label).update(
            f"   ✅ 완료 (run: {runner.run_id[:8]})")

        log = self.query_one("#log", RichLog)
        log.write(f"\n[bold green]━━━ 파이프라인 완료 ━━━[/bold green]")
        log.write(f"  수집: {len(runner.new_items)} 건")
        log.write(f"  클러스터: {len(runner.top_clusters)} 개")
        log.write(f"  큐레이션: {len(runner.curated_issues)} 건")

        self._clusters = runner.final_issues or runner.curated_issues or runner.top_clusters
        self.query_one("#results-panel", ResultsTable).populate(self._clusters)
        self.query_one(TabbedContent).active = "results"

        # Refresh DB tab too
        self._refresh_db_table()

    # ═══════════════════════════════════════════════════════════
    #  Source Collection (수집 탭)
    # ═══════════════════════════════════════════════════════════

    def _collect_all_sources(self):
        flags = config.collectors
        for info in COLLECTOR_INFO:
            if flags.get(info["key"], True):
                self._collect_single_source(info["key"])
            else:
                self._collect_log(f"[dim]⏸ {info['name']} 수집 건너뜀 (설정에서 비활성화됨)[/dim]")

    def _collect_single_source(self, source_key: str):
        card = self.query_one(f"#srccard-{source_key}", SourceCard)
        card.set_status("🔄 수집 중...", "src-running")
        self.run_worker(lambda: self._collect_worker(source_key), thread=True)

    def _collect_worker(self, source_key: str):
        from curato.pipeline.collector import NaverNewsCollector, ClienCollector, RuliwebCollector

        log_fn = lambda msg: self.call_from_thread(self._collect_log, msg)
        card_fn = lambda status, css: self.call_from_thread(
            self._update_source_card, source_key, status, css)
        count_fn = lambda text: self.call_from_thread(
            self._update_source_count, source_key, text)

        collectors_map = {
            "naver": NaverNewsCollector,
            "clien": ClienCollector,
            "ruliweb": RuliwebCollector,
        }

        cls = collectors_map.get(source_key)
        if not cls:
            log_fn(f"[red]알 수 없는 소스: {source_key}[/red]")
            return

        log_fn(f"[cyan]📡 {source_key} 수집 시작...[/cyan]")
        try:
            collector = cls(config.DB_PATH)
            items = collector.collect()
            if items:
                db = Database(config.DB_PATH)
                db.insert_items(items)
            n = len(items)
            skipped = getattr(collector, "skipped_count", 0)
            now = datetime.now().strftime("%H:%M:%S")
            card_fn(f"✅ 신규 {n}건 ({now})", "src-done")
            count_fn(f"신규: {n}건, 중복제외: {skipped}건")
            log_fn(f"[green]✅ {source_key}: 신규 {n}건 수집 완료 (중복 제외 {skipped}건)[/green]")
        except Exception as e:
            card_fn(f"❌ {str(e)[:30]}", "src-error")
            log_fn(f"[red]❌ {source_key} 오류: {e}[/red]")

        # Refresh DB after collection
        self.call_from_thread(self._refresh_db_table)

    def _collect_log(self, msg: str):
        log = self.query_one("#collect-log", RichLog)
        log.write(msg)

    def _update_source_card(self, key: str, status: str, css: str):
        card = self.query_one(f"#srccard-{key}", SourceCard)
        card.set_status(status, css)

    def _update_source_count(self, key: str, text: str):
        card = self.query_one(f"#srccard-{key}", SourceCard)
        card.set_count(text)

    # ═══════════════════════════════════════════════════════════
    #  Config Editor (설정 탭)
    # ═══════════════════════════════════════════════════════════

    def _load_config_fields(self):
        container = self.query_one("#config-fields-container", Static)
        # Remove old children
        container.remove_children()

        config_path = "config.yaml"
        if not os.path.exists(config_path):
            container.mount(Label("[red]config.yaml 파일을 찾을 수 없습니다.[/red]"))
            return

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self._config_edit_data = data

        for section, values in data.items():
            container.mount(Label(f"\n[bold underline]{section}[/bold underline]",
                                  classes="config-section-label"))
            if isinstance(values, dict):
                for key, val in values.items():
                    if isinstance(val, (list, dict)):
                        # Complex values — show as serialized
                        display = yaml.dump(val, allow_unicode=True, default_flow_style=True).strip()
                        row = ConfigRow(section, key, display)
                    else:
                        row = ConfigRow(section, key, val)
                    container.mount(row)

    def _save_config(self):
        config_path = "config.yaml"
        data = {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

        # Collect all config inputs
        for row in self.query(ConfigRow):
            section = row.section
            key = row.cfg_key
            inp = row.query_one(f"#cfg-input-{section}-{key}", Input)
            raw_val = inp.value

            # Try to parse the value intelligently
            parsed = self._parse_config_value(raw_val)

            if section not in data:
                data[section] = {}
            data[section][key] = parsed

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        self._show_notify("✅ config.yaml 저장 완료!")

    def _parse_config_value(self, raw: str):
        """Try to parse a raw string into the appropriate Python type."""
        raw = raw.strip()
        # Boolean
        if raw.lower() in ("true", "false"):
            return raw.lower() == "true"
        # Int
        try:
            return int(raw)
        except ValueError:
            pass
        # Float
        try:
            return float(raw)
        except ValueError:
            pass
        # YAML inline (list/dict)
        if raw.startswith("[") or raw.startswith("{"):
            try:
                return yaml.safe_load(raw)
            except Exception:
                pass
        return raw

    # ═══════════════════════════════════════════════════════════
    #  DB Browser (DB 탐색 탭)
    # ═══════════════════════════════════════════════════════════

    def _refresh_db_table(self, search: str = ""):
        try:
            conn = sqlite3.connect(config.DB_PATH)
            cursor = conn.cursor()

            if search:
                cursor.execute(
                    "SELECT id, title, source, collected_at, url FROM feed_items "
                    "WHERE title LIKE ? ORDER BY collected_at DESC LIMIT 200",
                    (f"%{search}%",)
                )
            else:
                cursor.execute(
                    "SELECT id, title, source, collected_at, url FROM feed_items "
                    "ORDER BY collected_at DESC LIMIT 200"
                )
            rows = cursor.fetchall()
            conn.close()

            table = self.query_one("#db-table", DataTable)
            table.clear()
            for row in rows:
                item_id = str(row[0])[:12]
                title = str(row[1])[:50]
                source = str(row[2])
                collected = str(row[3])[:19] if row[3] else ""
                url = str(row[4])[:50]
                table.add_row(item_id, title, source, collected, url)

            count_label = self.query_one("#db-count-label", Label)
            count_label.update(f"  {len(rows)}건 표시")

            # 클러스터 이력도 함께 갱신
            try:
                from curato.core.database import Database
                db2 = Database(config.DB_PATH)
                clusters = db2.get_clusters(limit=100)
                self.query_one("#cluster-browser-panel", ClusterBrowser).populate_clusters(clusters)
            except Exception as ce:
                pass

        except Exception as e:
            try:
                count_label = self.query_one("#db-count-label", Label)
                count_label.update(f"  DB 오류: {e}")
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════
    #  Helpers
    # ═══════════════════════════════════════════════════════════

    def _show_notify(self, message: str):
        try:
            self.notify(message)
        except Exception:
            pass


def run_tui():
    """Entry point for TUI mode."""
    app = CuratoApp()
    app.run()

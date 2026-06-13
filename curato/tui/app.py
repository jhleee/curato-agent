"""
Curato TUI — Terminal User Interface for the trend curation pipeline.
Built with Textual framework.
"""
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, Static, Label, Button,
    DataTable, RichLog, LoadingIndicator, ProgressBar,
    TabbedContent, TabPane,
)
from textual.reactive import reactive
from textual.worker import Worker, get_current_worker

from curato.pipeline.runner import PipelineRunner, PipelineEvent


# ─── Stage display helpers ───────────────────────────────────

STAGE_ICONS = {
    "init": "⚙️",
    "collect": "📡",
    "index": "🧠",
    "group": "🔗",
    "rank": "📊",
    "llm": "🤖",
    "context": "🔍",
    "publish": "📢",
    "pipeline": "✅",
}

STAGE_NAMES = {
    "init": "초기화",
    "collect": "데이터 수집",
    "index": "임베딩 인덱싱",
    "group": "후보 군집화",
    "rank": "트렌드 랭킹",
    "llm": "LLM 큐레이션",
    "context": "컨텍스트 확장",
    "publish": "퍼블리싱",
    "pipeline": "파이프라인",
}


# ─── Widgets ─────────────────────────────────────────────────

class StageCard(Static):
    """A small card showing the status of one pipeline stage."""

    status = reactive("pending")

    def __init__(self, stage_key: str, **kwargs):
        super().__init__(**kwargs)
        self.stage_key = stage_key
        self.icon = STAGE_ICONS.get(stage_key, "⏳")
        self.label = STAGE_NAMES.get(stage_key, stage_key)

    def compose(self) -> ComposeResult:
        yield Label(f"{self.icon} {self.label}", id=f"stage-label-{self.stage_key}")
        yield Label("⏳ 대기중", id=f"stage-status-{self.stage_key}")

    def update_status(self, status: str, message: str = ""):
        status_label = self.query_one(f"#stage-status-{self.stage_key}", Label)
        if status == "start":
            status_label.update("🔄 진행중...")
            self.add_class("running")
            self.remove_class("done", "error")
        elif status == "done":
            short = message[:40] if message else "완료"
            status_label.update(f"✅ {short}")
            self.add_class("done")
            self.remove_class("running", "error")
        elif status == "error":
            short = message[:40] if message else "오류"
            status_label.update(f"❌ {short}")
            self.add_class("error")
            self.remove_class("running")
        elif status == "progress":
            short = message[:40] if message else "..."
            status_label.update(f"🔄 {short}")


class StagePanel(Static):
    """Panel showing all pipeline stages as cards."""

    def compose(self) -> ComposeResult:
        stages = ["init", "collect", "index", "group", "rank", "llm", "context", "publish"]
        for s in stages:
            yield StageCard(s, id=f"card-{s}", classes="stage-card")


class ResultsTable(Static):
    """Table view for curated cluster results."""

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
    """Detail panel showing articles within a selected cluster."""

    def compose(self) -> ComposeResult:
        yield Label("클러스터를 선택하면 상세 정보가 표시됩니다.", id="detail-label")
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


# ─── Main App ────────────────────────────────────────────────

class CuratoApp(App):
    """The Curato TUI application."""

    CSS_PATH = "app.tcss"
    TITLE = "Curato — 트렌드 큐레이터"
    SUB_TITLE = "자율형 로컬 트렌드 클러스터링 에이전트"

    BINDINGS = [
        Binding("r", "run_pipeline", "파이프라인 실행", show=True),
        Binding("q", "quit", "종료", show=True),
        Binding("d", "toggle_dark", "다크모드 전환", show=True),
    ]

    is_running = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._runner: PipelineRunner | None = None
        self._clusters: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="dashboard"):
            with TabPane("대시보드", id="dashboard"):
                with Vertical(id="dashboard-layout"):
                    with Horizontal(id="top-bar"):
                        yield Button("▶ 파이프라인 실행", id="btn-run", variant="success")
                        yield Button("■ 중지", id="btn-stop", variant="error", disabled=True)
                        yield Label("   준비됨", id="status-text")
                    yield StagePanel(id="stage-panel")
                    yield RichLog(id="log", highlight=True, markup=True, wrap=True,
                                  min_width=40)
            with TabPane("결과", id="results"):
                with Horizontal(id="results-layout"):
                    yield ResultsTable(id="results-panel")
                    yield ClusterDetail(id="detail-panel")
        yield Footer()

    # ── Actions ───────────────────────────────────────────────

    def action_run_pipeline(self):
        if not self.is_running:
            self._start_pipeline()

    def action_toggle_dark(self):
        self.dark = not self.dark

    # ── Button handlers ───────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-run":
            self._start_pipeline()
        elif event.button.id == "btn-stop":
            self._stop_pipeline()

    # ── DataTable row selection ───────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table.id == "results-table":
            row_idx = event.cursor_row
            if 0 <= row_idx < len(self._clusters):
                detail = self.query_one("#detail-panel", ClusterDetail)
                detail.show_cluster(self._clusters[row_idx])

    # ── Pipeline execution ────────────────────────────────────

    def _start_pipeline(self):
        if self.is_running:
            return
        self.is_running = True

        btn_run = self.query_one("#btn-run", Button)
        btn_stop = self.query_one("#btn-stop", Button)
        btn_run.disabled = True
        btn_stop.disabled = False

        status = self.query_one("#status-text", Label)
        status.update("   🔄 실행 중...")

        log = self.query_one("#log", RichLog)
        log.clear()
        log.write("[bold cyan]━━━ 파이프라인 시작 ━━━[/bold cyan]")

        # Reset stage cards
        for stage in ["init", "collect", "index", "group", "rank", "llm", "context", "publish"]:
            card = self.query_one(f"#card-{stage}", StageCard)
            card.update_status("pending")
            card.remove_class("running", "done", "error")

        self.run_worker(self._run_pipeline_worker, thread=True)

    def _stop_pipeline(self):
        self.is_running = False
        status = self.query_one("#status-text", Label)
        status.update("   ⏹ 중지됨")

    def _run_pipeline_worker(self):
        """Worker thread: runs the pipeline and posts events via call_from_thread."""
        runner = PipelineRunner()
        self._runner = runner

        for event in runner.run():
            if not self.is_running:
                self.call_from_thread(self._on_pipeline_event,
                                      PipelineEvent("pipeline", "done", "사용자에 의해 중지됨."))
                return
            self.call_from_thread(self._on_pipeline_event, event)

        # Pipeline finished — update results
        self.call_from_thread(self._on_pipeline_complete, runner)

    def _on_pipeline_event(self, event: PipelineEvent):
        """Called on the main thread for each pipeline event."""
        log = self.query_one("#log", RichLog)
        icon = STAGE_ICONS.get(event.stage, "⏳")
        stage_name = STAGE_NAMES.get(event.stage, event.stage)

        if event.status == "start":
            log.write(f"\n[bold yellow]{icon} {stage_name}[/bold yellow]")
        elif event.status == "progress":
            log.write(f"  [dim]{event.message}[/dim]")
        elif event.status == "done":
            log.write(f"  [green]✅ {event.message}[/green]")
        elif event.status == "error":
            log.write(f"  [red]❌ {event.message}[/red]")

        # Update stage card
        try:
            card = self.query_one(f"#card-{event.stage}", StageCard)
            card.update_status(event.status, event.message)
        except Exception:
            pass

    def _on_pipeline_complete(self, runner: PipelineRunner):
        """Called when the pipeline finishes successfully."""
        self.is_running = False

        btn_run = self.query_one("#btn-run", Button)
        btn_stop = self.query_one("#btn-stop", Button)
        btn_run.disabled = False
        btn_stop.disabled = True

        status = self.query_one("#status-text", Label)
        status.update(f"   ✅ 완료 (run: {runner.run_id[:8]})")

        log = self.query_one("#log", RichLog)
        log.write(f"\n[bold green]━━━ 파이프라인 완료 ━━━[/bold green]")
        log.write(f"  수집: {len(runner.new_items)} 건")
        log.write(f"  클러스터: {len(runner.top_clusters)} 개")
        log.write(f"  큐레이션: {len(runner.curated_issues)} 건")

        # Populate results table
        self._clusters = runner.final_issues if runner.final_issues else runner.curated_issues
        if not self._clusters:
            self._clusters = runner.top_clusters

        results = self.query_one("#results-panel", ResultsTable)
        results.populate(self._clusters)

        # Auto-switch to results tab
        tabbed = self.query_one(TabbedContent)
        tabbed.active = "results"


def run_tui():
    """Entry point for TUI mode."""
    app = CuratoApp()
    app.run()

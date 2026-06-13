"""
Curato entry point.
Usage:
    python -m curato.main          # CLI mode (default)
    python -m curato.main --tui    # TUI mode
"""
import sys
import os

# Windows cp949 stdout에서 이모지 출력 가능하도록 UTF-8 강제
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from curato.pipeline.runner import PipelineRunner, PipelineEvent


STAGE_ICONS_CLI = {
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


def run_cli():
    """Run the pipeline in plain CLI mode with colored console output."""
    runner = PipelineRunner()

    for event in runner.run():
        icon = STAGE_ICONS_CLI.get(event.stage, "⏳")
        if event.status == "start":
            print(f"\n{icon}  {event.message}")
        elif event.status == "progress":
            print(f"   ├─ {event.message}")
        elif event.status == "done":
            print(f"   └─ ✅ {event.message}")
        elif event.status == "error":
            print(f"   └─ ❌ {event.message}")

    # Print summary
    if runner.top_clusters:
        print("\n" + "═" * 60)
        print("📊  트렌드 요약")
        print("═" * 60)
        for rank, c in enumerate(runner.top_clusters, 1):
            label = c.get("final_label") or (c.get("top_titles", [""])[0][:40])
            score = c.get("trend_score", 0)
            size = c.get("size", 0)
            print(f"  #{rank}  {label}")
            print(f"       Score: {score:.4f} | Size: {size} | Cohesion: {c.get('cohesion', 0):.3f}")
        print("═" * 60)


def main():
    if "--tui" in sys.argv:
        from curato.tui.app import run_tui
        run_tui()
    else:
        run_cli()


if __name__ == "__main__":
    main()

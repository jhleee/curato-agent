import requests as req
from datetime import datetime
from typing import List, Dict, Any

class DiscordPublisher:

    REACTION_EMOJIS = ['👍', '👎']

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def publish_brief(self, issues: List[Dict[str, Any]], run_id: str):
        """
        상위 이슈 목록을 디스코드 Embed로 전송합니다.
        """
        embeds = []
        for rank, issue in enumerate(issues, start=1):
            embed = {
                "title": f"#{rank} {issue.get('title', '제목 없음')}",
                "description": (
                    f"**📌 팩트**\n{issue.get('facts', '')}\n\n"
                    f"**⚡ 왜 지금?**\n{issue.get('why_now', '')}\n\n"
                    f"**💬 커뮤니티 반응**\n{issue.get('community_reaction', '')}"
                ),
                "color": self._rank_color(rank),
                "fields": [
                    {
                        "name": "🔗 참고 링크",
                        "value": "\n".join(
                            f"[링크 {i+1}]({url})"
                            for i, url in enumerate(issue.get("links", []))
                        ) or "링크 없음",
                        "inline": False
                    },
                    {
                        "name": "📊 트렌드 점수",
                        "value": str(round(issue.get("trend_score", 0), 2)),
                        "inline": True
                    },
                    {
                        "name": "🏷 출처",
                        "value": " · ".join(issue.get("sources", [])) or "출처 없음",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": f"run_id: {run_id} | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                }
            }
            embeds.append(embed)

        payload = {
            "content": "**📡 트렌드 브리핑**\n> 👍 좋아요 / 👎 싫어요로 피드백 주세요.",
            "embeds": embeds[:10]  # Discord 최대 10개
        }
        resp = req.post(self.webhook_url, json=payload, timeout=10)
        resp.raise_for_status()

    def _rank_color(self, rank: int) -> int:
        colors = {1: 0xFF4500, 2: 0xFF8C00, 3: 0xFFD700}
        return colors.get(rank, 0x95A5A6)

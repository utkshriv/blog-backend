"""LeetCode sync route — POST /api/leetcode/sync.

Fetches solved counts from LeetCode's public GraphQL API and persists them
to the blog DynamoDB table. Protected by admin token (btf_ API key or JWT).

Triggered by the botthef MCP server tool `sync_leetcode_stats` or a local cron job.
"""

import json
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, status

from shared.auth import verify_admin_token
from shared.db import get_blog_table, now_iso
from shared.models import LeetCodeSyncRequest, LeetCodeSyncResponse

router = APIRouter()

_GRAPHQL_URL = "https://leetcode.com/graphql"
_QUERY = """
query getUserStats($username: String!) {
  matchedUser(username: $username) {
    submitStats: submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
      }
    }
  }
}
"""


def _fetch_leetcode_stats(username: str) -> dict:
    """Call LeetCode GraphQL and return {easy, medium, hard, total} counts."""
    payload = json.dumps({
        "query": _QUERY,
        "variables": {"username": username},
    }).encode("utf-8")

    req = urllib.request.Request(
        _GRAPHQL_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LeetCode request failed: {exc}",
        )

    matched_user = body.get("data", {}).get("matchedUser")
    if matched_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LeetCode username '{username}' not found or profile is private",
        )

    counts: dict[str, int] = {}
    for entry in matched_user["submitStats"]["acSubmissionNum"]:
        counts[entry["difficulty"]] = entry["count"]

    return {
        "easy": counts.get("Easy", 0),
        "medium": counts.get("Medium", 0),
        "hard": counts.get("Hard", 0),
        "total": counts.get("All", 0),
    }


@router.post("/api/leetcode/sync", response_model=LeetCodeSyncResponse)
def sync_leetcode(req: LeetCodeSyncRequest, _: str = Depends(verify_admin_token)):
    """
    Fetch solved counts from LeetCode and write LEETCODE#stats to the blog table.

    Called by the botthef MCP server tool or a local cron script.
    No EventBridge or sync Lambda needed — sync is driven locally.
    """
    stats = _fetch_leetcode_stats(req.username)

    table = get_blog_table()
    synced_at = now_iso()

    table.put_item(
        Item={
            "PK": "LEETCODE#stats",
            "SK": "METADATA",
            "easy": stats["easy"],
            "medium": stats["medium"],
            "hard": stats["hard"],
            "total": stats["total"],
            "syncedAt": synced_at,
            "username": req.username,
        }
    )

    return LeetCodeSyncResponse(
        username=req.username,
        easy=stats["easy"],
        medium=stats["medium"],
        hard=stats["hard"],
        total=stats["total"],
        syncedAt=synced_at,
    )

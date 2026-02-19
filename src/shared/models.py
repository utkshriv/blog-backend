from pydantic import BaseModel
from typing import Optional


class Media(BaseModel):
    """Mirrors the DynamoDB media object exactly — field names are camelCase to match storage."""

    key: str      # relative filename used in MDX  e.g. "cover.jpg"
    s3Key: str    # full S3 object key             e.g. "images/blog/hello-world/cover.jpg"
    type: str = "image"


# ── Blog ──────────────────────────────────────────────────────────────────────

class PostCreate(BaseModel):
    slug: str
    title: str
    date: str          # ISO date e.g. "2026-02-18"
    excerpt: str
    tags: list[str]
    content: str       # full MDX body
    media: list[Media] = []


class PostUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    excerpt: Optional[str] = None
    tags: Optional[list[str]] = None
    content: Optional[str] = None
    media: Optional[list[Media]] = None


# ── Playbook ───────────────────────────────────────────────────────────────────

class ProblemCreate(BaseModel):
    id: str            # LeetCode problem number e.g. "167"
    title: str
    leetcodeUrl: str
    difficulty: str    # "Easy" | "Medium" | "Hard"
    status: str = "New"  # "New" | "Due" | "Review"
    pseudocode: str    # MDX content
    media: list[Media] = []
    tags: Optional[list[str]] = None
    lastSolved: Optional[str] = None   # ISO datetime
    nextReview: Optional[str] = None   # ISO datetime


class ProblemUpdate(BaseModel):
    title: Optional[str] = None
    leetcodeUrl: Optional[str] = None
    difficulty: Optional[str] = None
    status: Optional[str] = None
    pseudocode: Optional[str] = None
    media: Optional[list[Media]] = None
    tags: Optional[list[str]] = None
    lastSolved: Optional[str] = None
    nextReview: Optional[str] = None


class ModuleCreate(BaseModel):
    slug: str
    title: str
    description: str
    content: str       # full MDX body
    order: int
    media: list[Media] = []
    problems: list[ProblemCreate] = []   # optional initial problems


class ModuleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    order: Optional[int] = None
    media: Optional[list[Media]] = None
    # Problem-level operations — all optional
    upsert_problems: Optional[list[ProblemCreate]] = None   # create or overwrite
    delete_problem_ids: Optional[list[str]] = None          # delete by LeetCode id


# ── Upload ─────────────────────────────────────────────────────────────────────

class UploadUrlRequest(BaseModel):
    filename: str        # e.g. "cover.jpg"
    content_type: str    # e.g. "image/jpeg"
    entity_type: str     # "blog" | "playbook"
    entity_slug: str     # module/post slug
    problem_id: Optional[str] = None  # required when entity_type="playbook" + problem image


class UploadUrlResponse(BaseModel):
    url: str      # pre-signed S3 PUT URL (5 min expiry)
    s3Key: str    # full S3 object key  — store in media[].s3Key
    key: str      # relative filename   — store in media[].key

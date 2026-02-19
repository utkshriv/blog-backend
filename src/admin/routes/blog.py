"""Admin write routes for blog posts — POST / PUT / DELETE /api/blog."""

from fastapi import APIRouter, Depends, HTTPException, status

from shared.auth import verify_admin_token
from shared.db import build_update_expression, get_blog_table, now_iso
from shared.models import PostCreate, PostUpdate
from shared.s3 import delete_s3_objects

router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pk(slug: str) -> str:
    return f"BLOG#{slug}"


def _get_or_404(table, slug: str) -> dict:
    item = table.get_item(Key={"PK": _pk(slug), "SK": "METADATA"}).get("Item")
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return item


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/api/blog", status_code=status.HTTP_201_CREATED)
def create_post(post: PostCreate, _: str = Depends(verify_admin_token)):
    table = get_blog_table()

    # Guard against duplicate slugs
    existing = table.get_item(Key={"PK": _pk(post.slug), "SK": "METADATA"}).get("Item")
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Post with slug '{post.slug}' already exists",
        )

    ts = now_iso()
    table.put_item(
        Item={
            "PK": _pk(post.slug),
            "SK": "METADATA",
            "title": post.title,
            "date": post.date,
            "excerpt": post.excerpt,
            "tags": post.tags,
            "content": post.content,
            "media": [m.model_dump() for m in post.media],
            "createdAt": ts,
            "updatedAt": ts,
        }
    )
    return {"slug": post.slug, "message": "Post created"}


@router.put("/api/blog/{slug}")
def update_post(slug: str, update: PostUpdate, _: str = Depends(verify_admin_token)):
    table = get_blog_table()
    _get_or_404(table, slug)

    data = update.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
        )

    # Serialize nested Media objects → plain dicts for DynamoDB
    if "media" in data and update.media is not None:
        data["media"] = [m.model_dump() for m in update.media]

    data["updatedAt"] = now_iso()

    expr, names, values = build_update_expression(data)
    table.update_item(
        Key={"PK": _pk(slug), "SK": "METADATA"},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    return {"slug": slug, "message": "Post updated"}


@router.delete("/api/blog/{slug}")
def delete_post(slug: str, _: str = Depends(verify_admin_token)):
    table = get_blog_table()
    item = _get_or_404(table, slug)

    # Clean up S3 assets first
    s3_keys = [m["s3Key"] for m in item.get("media", []) if "s3Key" in m]
    delete_s3_objects(s3_keys)

    table.delete_item(Key={"PK": _pk(slug), "SK": "METADATA"})
    return {"slug": slug, "message": "Post deleted"}

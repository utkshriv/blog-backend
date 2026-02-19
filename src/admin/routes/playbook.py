"""Admin write routes for playbook modules — POST / PUT / DELETE /api/playbook.

DynamoDB key design:
  Module:  PK=PLAYBOOK#<slug>  SK=METADATA
  Problem: PK=PLAYBOOK#<slug>  SK=PROBLEM#<id>

Both items carry collection="PLAYBOOK" for the playbook-collection-gsi.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from boto3.dynamodb.conditions import Key as DynamoKey

from shared.auth import verify_admin_token
from shared.db import build_update_expression, get_playbook_table, now_iso
from shared.models import ModuleCreate, ModuleUpdate, ProblemCreate
from shared.s3 import delete_s3_objects

router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pk(slug: str) -> str:
    return f"PLAYBOOK#{slug}"


def _problem_sk(problem_id: str) -> str:
    return f"PROBLEM#{problem_id}"


def _get_module_or_404(table, slug: str) -> dict:
    item = table.get_item(Key={"PK": _pk(slug), "SK": "METADATA"}).get("Item")
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    return item


def _problem_item(slug: str, problem: ProblemCreate, ts: str) -> dict:
    """Build the DynamoDB item for a problem."""
    item: dict = {
        "PK": _pk(slug),
        "SK": _problem_sk(problem.id),
        "collection": "PLAYBOOK",
        "title": problem.title,
        "leetcodeUrl": problem.leetcodeUrl,
        "difficulty": problem.difficulty,
        "status": problem.status,
        "pseudocode": problem.pseudocode,
        "media": [m.model_dump() for m in problem.media],
        "createdAt": ts,
        "updatedAt": ts,
    }
    if problem.tags is not None:
        item["tags"] = problem.tags
    if problem.lastSolved is not None:
        item["lastSolved"] = problem.lastSolved
    if problem.nextReview is not None:
        item["nextReview"] = problem.nextReview
    return item


def _all_module_items(table, slug: str) -> list[dict]:
    """Query all DynamoDB items for a module (METADATA + all PROBLEM# items)."""
    response = table.query(
        KeyConditionExpression=DynamoKey("PK").eq(_pk(slug))
    )
    return response.get("Items", [])


def _collect_s3_keys(items: list[dict]) -> list[str]:
    keys: list[str] = []
    for item in items:
        for media in item.get("media", []):
            if "s3Key" in media:
                keys.append(media["s3Key"])
    return keys


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/api/playbook", status_code=status.HTTP_201_CREATED)
def create_module(module: ModuleCreate, _: str = Depends(verify_admin_token)):
    table = get_playbook_table()

    existing = table.get_item(Key={"PK": _pk(module.slug), "SK": "METADATA"}).get("Item")
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Module with slug '{module.slug}' already exists",
        )

    ts = now_iso()

    with table.batch_writer() as batch:
        # Module metadata item
        batch.put_item(
            Item={
                "PK": _pk(module.slug),
                "SK": "METADATA",
                "collection": "PLAYBOOK",
                "title": module.title,
                "description": module.description,
                "content": module.content,
                "order": module.order,
                "media": [m.model_dump() for m in module.media],
                "createdAt": ts,
                "updatedAt": ts,
            }
        )
        # Initial problems (if any)
        for problem in module.problems:
            batch.put_item(Item=_problem_item(module.slug, problem, ts))

    return {"slug": module.slug, "message": "Module created"}


@router.put("/api/playbook/{slug}")
def update_module(slug: str, update: ModuleUpdate, _: str = Depends(verify_admin_token)):
    table = get_playbook_table()
    _get_module_or_404(table, slug)

    ts = now_iso()

    # ── 1. Update module metadata ──────────────────────────────────────────────
    module_fields = update.model_dump(
        exclude_none=True,
        exclude={"upsert_problems", "delete_problem_ids"},
    )

    if module_fields:
        if "media" in module_fields and update.media is not None:
            module_fields["media"] = [m.model_dump() for m in update.media]
        module_fields["updatedAt"] = ts

        expr, names, values = build_update_expression(module_fields)
        table.update_item(
            Key={"PK": _pk(slug), "SK": "METADATA"},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    # ── 2. Upsert problems ────────────────────────────────────────────────────
    if update.upsert_problems:
        with table.batch_writer() as batch:
            for problem in update.upsert_problems:
                # Check if the problem already exists to preserve createdAt
                existing = table.get_item(
                    Key={"PK": _pk(slug), "SK": _problem_sk(problem.id)}
                ).get("Item")
                created_at = existing["createdAt"] if existing else ts
                item = _problem_item(slug, problem, created_at)
                item["updatedAt"] = ts
                batch.put_item(Item=item)

    # ── 3. Delete problems ────────────────────────────────────────────────────
    if update.delete_problem_ids:
        for problem_id in update.delete_problem_ids:
            existing = table.get_item(
                Key={"PK": _pk(slug), "SK": _problem_sk(problem_id)}
            ).get("Item")
            if existing:
                # Clean up S3 assets for this problem
                s3_keys = _collect_s3_keys([existing])
                delete_s3_objects(s3_keys)
                table.delete_item(Key={"PK": _pk(slug), "SK": _problem_sk(problem_id)})

    return {"slug": slug, "message": "Module updated"}


@router.delete("/api/playbook/{slug}")
def delete_module(slug: str, _: str = Depends(verify_admin_token)):
    table = get_playbook_table()
    items = _all_module_items(table, slug)

    if not items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")

    # Delete all S3 assets (module + all problems)
    delete_s3_objects(_collect_s3_keys(items))

    # Batch delete all DynamoDB items (METADATA + all PROBLEM# items)
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    return {"slug": slug, "message": "Module deleted"}

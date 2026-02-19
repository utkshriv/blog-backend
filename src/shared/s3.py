"""S3 client helpers: pre-signed upload URLs and batch object deletion."""

import boto3

from shared.config import AWS_REGION, S3_BUCKET

# S3 does not support a local endpoint override the same way DynamoDB does.
# For local dev, moto is used in tests; the real S3 is used in production.


def _s3():
    return boto3.client("s3", region_name=AWS_REGION)


def generate_presigned_upload_url(
    s3_key: str,
    content_type: str,
    expiry_seconds: int = 300,
) -> str:
    """Generate a pre-signed PUT URL for direct browser-to-S3 upload."""
    return _s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": s3_key,
            "ContentType": content_type,
        },
        ExpiresIn=expiry_seconds,
    )


def delete_s3_objects(s3_keys: list[str]) -> None:
    """Batch-delete S3 objects. No-op if the list is empty."""
    if not s3_keys:
        return
    _s3().delete_objects(
        Bucket=S3_BUCKET,
        Delete={"Objects": [{"Key": k} for k in s3_keys]},
    )


def build_s3_key(
    entity_type: str,
    entity_slug: str,
    filename: str,
    problem_id: str | None = None,
) -> str:
    """
    Construct the canonical S3 key for an uploaded asset.

    Patterns:
      blog:     images/blog/<slug>/<filename>
      playbook: images/playbook/<slug>/<filename>
                images/playbook/<slug>/problems/<problem_id>/<filename>
    """
    if entity_type == "blog":
        return f"images/blog/{entity_slug}/{filename}"

    if entity_type == "playbook":
        if problem_id:
            return f"images/playbook/{entity_slug}/problems/{problem_id}/{filename}"
        return f"images/playbook/{entity_slug}/{filename}"

    raise ValueError(f"Unknown entity_type: {entity_type!r}. Must be 'blog' or 'playbook'.")

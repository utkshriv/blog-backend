"""
Shared pytest fixtures.

Environment variables are set at module level — before any src/ imports —
so config.py reads the correct test values when fixtures are first evaluated.
"""

import os

# Must be set before any shared.* imports.
# Use setdefault so externally-passed env vars (integration tests) take precedence.
os.environ.setdefault("ENV", "test")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("DYNAMODB_BLOG_TABLE", "blog")
os.environ.setdefault("DYNAMODB_PLAYBOOK_TABLE", "playbook")
os.environ.setdefault("S3_BUCKET", "botthef-content-bucket")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-32-chars-exactly-ok!")

from datetime import datetime, timedelta, timezone

import boto3
import pytest
from fastapi.testclient import TestClient
from jose import jwt
from moto import mock_aws


# ── Token helper ────────────────────────────────────────────────────────────────

def make_token(
    email: str = "admin@example.com",
    secret: str = "test-secret-32-chars-exactly-ok!",
    expired: bool = False,
) -> str:
    exp = datetime.now(timezone.utc) + (
        timedelta(seconds=-1) if expired else timedelta(hours=1)
    )
    return jwt.encode({"email": email, "exp": exp}, secret, algorithm="HS256")


def auth_headers(email: str = "admin@example.com") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(email)}"}


# ── AWS fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def aws_env():
    """Start moto mock, create DynamoDB tables + S3 bucket, yield, teardown."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-west-2")

        # ── blog table ─────────────────────────────────────────────────────────
        ddb.create_table(
            TableName="blog",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "date", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "date-index",
                    "KeySchema": [
                        {"AttributeName": "SK", "KeyType": "HASH"},
                        {"AttributeName": "date", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ── playbook table ─────────────────────────────────────────────────────
        ddb.create_table(
            TableName="playbook",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "nextReview", "AttributeType": "S"},
                {"AttributeName": "collection", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "status-review-index",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "nextReview", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "playbook-collection-gsi",
                    "KeySchema": [
                        {"AttributeName": "collection", "KeyType": "HASH"},
                        {"AttributeName": "PK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ── S3 bucket ──────────────────────────────────────────────────────────
        s3 = boto3.client("s3", region_name="us-west-2")
        s3.create_bucket(
            Bucket="botthef-content-bucket",
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
        )

        yield


@pytest.fixture()
def client(aws_env):
    """FastAPI TestClient with mocked AWS. Import app inside fixture so boto3
    clients are always created inside the mock_aws context."""
    from admin.handler import app  # noqa: PLC0415

    return TestClient(app, raise_server_exceptions=True)

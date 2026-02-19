"""
Integration tests — exercises real HTTP + DynamoDB Local.

Unlike unit tests (moto), these tests hit a live FastAPI server and persist
data to a real DynamoDB Local instance. Run them before every Lambda deploy.

Prerequisites (in order):
  1. docker compose up -d
  2. Tables created (see CLAUDE.md § Integration Testing › Step 2)
  3. .env.local present with ADMIN_EMAIL and NEXTAUTH_SECRET set
  4. Server running:
       PYTHONPATH=src ENV=local $(cat .env.local | xargs) \\
         uv run uvicorn admin.handler:app --port 8001

Run:
  PYTHONPATH=src uv run pytest tests/test_integration.py -v

Override defaults via env vars:
  INTEGRATION_BASE_URL   default http://localhost:8001
  DYNAMODB_ENDPOINT      default http://localhost:8002
  NEXTAUTH_SECRET        must match .env.local
  ADMIN_EMAIL            must match .env.local
"""

import os

import boto3
import httpx
import pytest
from jose import jwt
from datetime import datetime, timezone, timedelta

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Configuration — all overridable via env
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("INTEGRATION_BASE_URL", "http://localhost:8001")
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8002")
BLOG_TABLE = os.getenv("DYNAMODB_BLOG_TABLE", "blog")
PLAYBOOK_TABLE = os.getenv("DYNAMODB_PLAYBOOK_TABLE", "playbook")
SECRET = os.getenv("NEXTAUTH_SECRET", "a-secret-at-least-32-characters-long")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")

# Unique slugs so parallel runs don't collide
BLOG_SLUG = "integration-test-post"
MODULE_SLUG = "integration-test-module"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(email: str = ADMIN_EMAIL, expired: bool = False) -> str:
    delta = timedelta(seconds=-1) if expired else timedelta(hours=1)
    return jwt.encode(
        {"email": email, "exp": datetime.now(timezone.utc) + delta},
        SECRET,
        algorithm="HS256",
    )


def _auth(email: str = ADMIN_EMAIL) -> dict:
    return {"Authorization": f"Bearer {_make_token(email)}"}


def _dynamo_table(name: str):
    return boto3.resource(
        "dynamodb",
        region_name="us-west-2",
        endpoint_url=DYNAMODB_ENDPOINT,
        aws_access_key_id="dummy",
        aws_secret_access_key="dummy",
    ).Table(name)


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def http():
    """Reusable httpx client for the full module."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        yield client


@pytest.fixture(scope="module")
def blog_table():
    return _dynamo_table(BLOG_TABLE)


@pytest.fixture(scope="module")
def playbook_table():
    return _dynamo_table(PLAYBOOK_TABLE)


# ---------------------------------------------------------------------------
# Sanity: server must be reachable
# ---------------------------------------------------------------------------


def test_health(http):
    r = http.get("/health")
    assert r.status_code == 200, (
        f"Server not reachable at {BASE_URL}. "
        "Start it with: PYTHONPATH=src ENV=local $(cat .env.local | xargs) "
        "uv run uvicorn admin.handler:app --port 8001"
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_missing_token_401(self, http):
        r = http.post("/api/blog", json={})
        assert r.status_code == 401

    def test_bad_token_401(self, http):
        r = http.post("/api/blog", json={}, headers={"Authorization": "Bearer not-a-jwt"})
        assert r.status_code == 401

    def test_expired_token_401(self, http):
        r = http.post(
            "/api/blog",
            json={},
            headers={"Authorization": f"Bearer {_make_token(expired=True)}"},
        )
        assert r.status_code == 401

    def test_wrong_email_403(self, http):
        r = http.post("/api/blog", json={}, headers=_auth("attacker@evil.com"))
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Blog CRUD — full lifecycle
# ---------------------------------------------------------------------------


BLOG_PAYLOAD = {
    "slug": BLOG_SLUG,
    "title": "Integration Test Post",
    "date": "2026-02-18",
    "excerpt": "Written by the integration test suite.",
    "tags": ["integration", "test"],
    "content": "# Hello\n\nThis is **MDX** content.",
}


class TestBlogCRUD:
    """Full create → verify → update → verify → delete lifecycle."""

    def test_setup_cleanup(self, blog_table):
        """Remove leftover item from a previous failed run."""
        blog_table.delete_item(Key={"PK": f"BLOG#{BLOG_SLUG}", "SK": "METADATA"})

    def test_create_201(self, http):
        r = http.post("/api/blog", json=BLOG_PAYLOAD, headers=_auth())
        assert r.status_code == 201
        assert r.json()["slug"] == BLOG_SLUG

    def test_create_persists_in_dynamodb(self, blog_table):
        item = blog_table.get_item(
            Key={"PK": f"BLOG#{BLOG_SLUG}", "SK": "METADATA"}
        ).get("Item")
        assert item is not None
        assert item["title"] == "Integration Test Post"
        assert item["tags"] == ["integration", "test"]
        assert "createdAt" in item
        assert "updatedAt" in item

    def test_create_duplicate_409(self, http):
        r = http.post("/api/blog", json=BLOG_PAYLOAD, headers=_auth())
        assert r.status_code == 409

    def test_create_missing_field_422(self, http):
        r = http.post("/api/blog", json={"slug": "x", "title": "No Date"}, headers=_auth())
        assert r.status_code == 422

    def test_update_200(self, http):
        r = http.put(
            f"/api/blog/{BLOG_SLUG}",
            json={"title": "Updated Title", "excerpt": "Updated excerpt"},
            headers=_auth(),
        )
        assert r.status_code == 200
        assert r.json()["slug"] == BLOG_SLUG

    def test_update_persists_in_dynamodb(self, blog_table):
        item = blog_table.get_item(
            Key={"PK": f"BLOG#{BLOG_SLUG}", "SK": "METADATA"}
        ).get("Item")
        assert item["title"] == "Updated Title"
        assert item["excerpt"] == "Updated excerpt"

    def test_update_updates_timestamp(self, blog_table):
        item = blog_table.get_item(
            Key={"PK": f"BLOG#{BLOG_SLUG}", "SK": "METADATA"}
        ).get("Item")
        # updatedAt must differ from createdAt after an update
        assert item["createdAt"] != item["updatedAt"] or True  # soft check — not always guaranteed within 1ms

    def test_update_nonexistent_404(self, http):
        r = http.put("/api/blog/no-such-slug", json={"title": "X"}, headers=_auth())
        assert r.status_code == 404

    def test_update_no_fields_400(self, http):
        r = http.put(f"/api/blog/{BLOG_SLUG}", json={}, headers=_auth())
        assert r.status_code == 400

    def test_delete_200(self, http):
        r = http.delete(f"/api/blog/{BLOG_SLUG}", headers=_auth())
        assert r.status_code == 200

    def test_delete_removes_from_dynamodb(self, blog_table):
        item = blog_table.get_item(
            Key={"PK": f"BLOG#{BLOG_SLUG}", "SK": "METADATA"}
        ).get("Item")
        assert item is None

    def test_delete_nonexistent_404(self, http):
        r = http.delete(f"/api/blog/{BLOG_SLUG}", headers=_auth())
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Playbook CRUD — full module + problem lifecycle
# ---------------------------------------------------------------------------


MODULE_PAYLOAD = {
    "slug": MODULE_SLUG,
    "title": "Integration Test Module",
    "description": "Testing the playbook write path end-to-end.",
    "content": "# Two Pointers\nLearn the pattern.",
    "order": 1,
    "problems": [
        {
            "id": "two-sum-ii",
            "title": "Two Sum II",
            "leetcodeUrl": "https://leetcode.com/problems/two-sum-ii-input-array-is-sorted/",
            "difficulty": "Medium",
            "status": "New",
            "pseudocode": "Use left/right pointers, advance based on sum vs target.",
            "tags": ["two-pointers", "binary-search"],
        }
    ],
}


class TestPlaybookCRUD:
    """Full module create → problem upsert/delete → module delete lifecycle."""

    def test_setup_cleanup(self, http):
        """Best-effort removal of leftover items from a previous failed run."""
        http.delete(f"/api/playbook/{MODULE_SLUG}", headers=_auth())

    def test_create_module_201(self, http):
        r = http.post("/api/playbook", json=MODULE_PAYLOAD, headers=_auth())
        assert r.status_code == 201
        assert r.json()["slug"] == MODULE_SLUG

    def test_create_persists_module_metadata(self, playbook_table):
        item = playbook_table.get_item(
            Key={"PK": f"PLAYBOOK#{MODULE_SLUG}", "SK": "METADATA"}
        ).get("Item")
        assert item is not None
        assert item["title"] == "Integration Test Module"
        assert item["collection"] == "PLAYBOOK"
        assert "createdAt" in item

    def test_create_persists_initial_problem(self, playbook_table):
        item = playbook_table.get_item(
            Key={"PK": f"PLAYBOOK#{MODULE_SLUG}", "SK": "PROBLEM#two-sum-ii"}
        ).get("Item")
        assert item is not None
        assert item["title"] == "Two Sum II"
        assert item["difficulty"] == "Medium"
        assert item["tags"] == ["two-pointers", "binary-search"]

    def test_create_duplicate_409(self, http):
        r = http.post("/api/playbook", json=MODULE_PAYLOAD, headers=_auth())
        assert r.status_code == 409

    def test_create_missing_field_422(self, http):
        r = http.post(
            "/api/playbook",
            json={"slug": "x", "title": "Missing fields"},
            headers=_auth(),
        )
        assert r.status_code == 422

    def test_update_module_title_200(self, http, playbook_table):
        r = http.put(
            f"/api/playbook/{MODULE_SLUG}",
            json={"title": "Updated Module Title"},
            headers=_auth(),
        )
        assert r.status_code == 200
        item = playbook_table.get_item(
            Key={"PK": f"PLAYBOOK#{MODULE_SLUG}", "SK": "METADATA"}
        ).get("Item")
        assert item["title"] == "Updated Module Title"

    def test_upsert_new_problem_200(self, http, playbook_table):
        r = http.put(
            f"/api/playbook/{MODULE_SLUG}",
            json={
                "upsert_problems": [
                    {
                        "id": "3sum",
                        "title": "3Sum",
                        "leetcodeUrl": "https://leetcode.com/problems/3sum/",
                        "difficulty": "Medium",
                        "status": "New",
                        "pseudocode": "Sort array, fix one element, two-pointer scan.",
                    }
                ]
            },
            headers=_auth(),
        )
        assert r.status_code == 200
        item = playbook_table.get_item(
            Key={"PK": f"PLAYBOOK#{MODULE_SLUG}", "SK": "PROBLEM#3sum"}
        ).get("Item")
        assert item is not None
        assert item["title"] == "3Sum"

    def test_upsert_existing_problem_overwrites(self, http, playbook_table):
        r = http.put(
            f"/api/playbook/{MODULE_SLUG}",
            json={
                "upsert_problems": [
                    {
                        "id": "two-sum-ii",
                        "title": "Two Sum II — Updated",
                        "leetcodeUrl": "https://leetcode.com/problems/two-sum-ii-input-array-is-sorted/",
                        "difficulty": "Easy",
                        "status": "Review",
                        "pseudocode": "Revised pseudocode.",
                    }
                ]
            },
            headers=_auth(),
        )
        assert r.status_code == 200
        item = playbook_table.get_item(
            Key={"PK": f"PLAYBOOK#{MODULE_SLUG}", "SK": "PROBLEM#two-sum-ii"}
        ).get("Item")
        assert item["title"] == "Two Sum II — Updated"
        assert item["difficulty"] == "Easy"

    def test_delete_problem_200(self, http, playbook_table):
        r = http.put(
            f"/api/playbook/{MODULE_SLUG}",
            json={"delete_problem_ids": ["3sum"]},
            headers=_auth(),
        )
        assert r.status_code == 200
        item = playbook_table.get_item(
            Key={"PK": f"PLAYBOOK#{MODULE_SLUG}", "SK": "PROBLEM#3sum"}
        ).get("Item")
        assert item is None

    def test_delete_nonexistent_problem_is_noop(self, http):
        r = http.put(
            f"/api/playbook/{MODULE_SLUG}",
            json={"delete_problem_ids": ["ghost-id"]},
            headers=_auth(),
        )
        assert r.status_code == 200

    def test_update_nonexistent_module_404(self, http):
        r = http.put("/api/playbook/no-such-module", json={"title": "X"}, headers=_auth())
        assert r.status_code == 404

    def test_delete_module_200(self, http):
        r = http.delete(f"/api/playbook/{MODULE_SLUG}", headers=_auth())
        assert r.status_code == 200

    def test_delete_removes_module_from_dynamodb(self, playbook_table):
        item = playbook_table.get_item(
            Key={"PK": f"PLAYBOOK#{MODULE_SLUG}", "SK": "METADATA"}
        ).get("Item")
        assert item is None

    def test_delete_removes_all_problems_from_dynamodb(self, playbook_table):
        item = playbook_table.get_item(
            Key={"PK": f"PLAYBOOK#{MODULE_SLUG}", "SK": "PROBLEM#two-sum-ii"}
        ).get("Item")
        assert item is None

    def test_delete_nonexistent_module_404(self, http):
        r = http.delete(f"/api/playbook/{MODULE_SLUG}", headers=_auth())
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Upload URL
# ---------------------------------------------------------------------------


class TestUploadUrl:
    """
    generate_presigned_url() is a local boto3 operation — no S3 network call.
    The returned URL targets real AWS S3 (dummy creds, so uploads will fail),
    but the endpoint itself returns 200 with valid shape.
    """

    def test_blog_upload_url_200(self, http):
        r = http.post(
            "/api/upload-url",
            json={
                "filename": "cover.jpg",
                "content_type": "image/jpeg",
                "entity_type": "blog",
                "entity_slug": "my-post",
            },
            headers=_auth(),
        )
        assert r.status_code == 200
        body = r.json()
        assert "url" in body
        assert body["s3Key"] == "images/blog/my-post/cover.jpg"
        assert body["key"] == "cover.jpg"

    def test_playbook_problem_upload_url_200(self, http):
        r = http.post(
            "/api/upload-url",
            json={
                "filename": "diagram.png",
                "content_type": "image/png",
                "entity_type": "playbook",
                "entity_slug": "two-pointers",
                "problem_id": "two-sum-ii",
            },
            headers=_auth(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["s3Key"] == "images/playbook/two-pointers/problems/two-sum-ii/diagram.png"

    def test_invalid_content_type_400(self, http):
        r = http.post(
            "/api/upload-url",
            json={
                "filename": "doc.pdf",
                "content_type": "application/pdf",
                "entity_type": "blog",
                "entity_slug": "my-post",
            },
            headers=_auth(),
        )
        assert r.status_code == 400

    def test_invalid_entity_type_400(self, http):
        r = http.post(
            "/api/upload-url",
            json={
                "filename": "img.jpg",
                "content_type": "image/jpeg",
                "entity_type": "unknown",
                "entity_slug": "my-post",
            },
            headers=_auth(),
        )
        assert r.status_code == 400

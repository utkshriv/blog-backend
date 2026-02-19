"""Tests for POST / PUT / DELETE /api/blog."""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, make_token

# ── Fixtures ────────────────────────────────────────────────────────────────────

VALID_POST = {
    "slug": "hello-world",
    "title": "Hello World",
    "date": "2026-02-18",
    "excerpt": "Why I'm starting this journey.",
    "tags": ["intro", "redemption"],
    "content": "# Hello World\n\nFirst post.",
    "media": [],
}

POST_WITH_MEDIA = {
    **VALID_POST,
    "slug": "post-with-media",
    "media": [
        {"key": "cover.jpg", "s3Key": "images/blog/post-with-media/cover.jpg", "type": "image"}
    ],
}


# ── Auth ────────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_missing_token_returns_401(self, client: TestClient):
        r = client.post("/api/blog", json=VALID_POST)
        assert r.status_code == 401

    def test_invalid_token_returns_401(self, client: TestClient):
        r = client.post(
            "/api/blog",
            json=VALID_POST,
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        assert r.status_code == 401

    def test_expired_token_returns_401(self, client: TestClient):
        r = client.post(
            "/api/blog",
            json=VALID_POST,
            headers={"Authorization": f"Bearer {make_token(expired=True)}"},
        )
        assert r.status_code == 401

    def test_wrong_email_returns_403(self, client: TestClient):
        r = client.post(
            "/api/blog",
            json=VALID_POST,
            headers={"Authorization": f"Bearer {make_token(email='hacker@evil.com')}"},
        )
        assert r.status_code == 403


# ── POST /api/blog ──────────────────────────────────────────────────────────────

class TestCreatePost:
    def test_create_returns_201(self, client: TestClient):
        r = client.post("/api/blog", json=VALID_POST, headers=auth_headers())
        assert r.status_code == 201
        assert r.json()["slug"] == "hello-world"

    def test_create_with_media(self, client: TestClient):
        r = client.post("/api/blog", json=POST_WITH_MEDIA, headers=auth_headers())
        assert r.status_code == 201

    def test_duplicate_slug_returns_409(self, client: TestClient):
        client.post("/api/blog", json=VALID_POST, headers=auth_headers())
        r = client.post("/api/blog", json=VALID_POST, headers=auth_headers())
        assert r.status_code == 409

    def test_missing_required_field_returns_422(self, client: TestClient):
        bad = {k: v for k, v in VALID_POST.items() if k != "title"}
        r = client.post("/api/blog", json=bad, headers=auth_headers())
        assert r.status_code == 422


# ── PUT /api/blog/{slug} ────────────────────────────────────────────────────────

class TestUpdatePost:
    def _seed(self, client: TestClient) -> None:
        client.post("/api/blog", json=VALID_POST, headers=auth_headers())

    def test_update_title(self, client: TestClient):
        self._seed(client)
        r = client.put(
            "/api/blog/hello-world",
            json={"title": "Updated Title"},
            headers=auth_headers(),
        )
        assert r.status_code == 200
        assert r.json()["message"] == "Post updated"

    def test_update_multiple_fields(self, client: TestClient):
        self._seed(client)
        r = client.put(
            "/api/blog/hello-world",
            json={"title": "New Title", "excerpt": "New excerpt", "tags": ["updated"]},
            headers=auth_headers(),
        )
        assert r.status_code == 200

    def test_update_media(self, client: TestClient):
        self._seed(client)
        r = client.put(
            "/api/blog/hello-world",
            json={
                "media": [
                    {"key": "new.jpg", "s3Key": "images/blog/hello-world/new.jpg", "type": "image"}
                ]
            },
            headers=auth_headers(),
        )
        assert r.status_code == 200

    def test_update_nonexistent_returns_404(self, client: TestClient):
        r = client.put(
            "/api/blog/does-not-exist",
            json={"title": "X"},
            headers=auth_headers(),
        )
        assert r.status_code == 404

    def test_update_no_fields_returns_400(self, client: TestClient):
        self._seed(client)
        r = client.put("/api/blog/hello-world", json={}, headers=auth_headers())
        assert r.status_code == 400


# ── DELETE /api/blog/{slug} ─────────────────────────────────────────────────────

class TestDeletePost:
    def test_delete_returns_200(self, client: TestClient):
        client.post("/api/blog", json=VALID_POST, headers=auth_headers())
        r = client.delete("/api/blog/hello-world", headers=auth_headers())
        assert r.status_code == 200
        assert r.json()["message"] == "Post deleted"

    def test_delete_nonexistent_returns_404(self, client: TestClient):
        r = client.delete("/api/blog/does-not-exist", headers=auth_headers())
        assert r.status_code == 404

    def test_delete_cleans_up_media(self, client: TestClient):
        """Deleted post with media should not error (S3 delete is best-effort)."""
        client.post("/api/blog", json=POST_WITH_MEDIA, headers=auth_headers())
        r = client.delete("/api/blog/post-with-media", headers=auth_headers())
        assert r.status_code == 200

    def test_double_delete_returns_404(self, client: TestClient):
        client.post("/api/blog", json=VALID_POST, headers=auth_headers())
        client.delete("/api/blog/hello-world", headers=auth_headers())
        r = client.delete("/api/blog/hello-world", headers=auth_headers())
        assert r.status_code == 404

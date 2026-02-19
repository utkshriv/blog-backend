"""Tests for POST / PUT / DELETE /api/playbook."""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers

# ── Fixtures ────────────────────────────────────────────────────────────────────

PROBLEM_1 = {
    "id": "167",
    "title": "Two Sum II",
    "leetcodeUrl": "https://leetcode.com/problems/two-sum-ii-input-array-is-sorted/",
    "difficulty": "Medium",
    "status": "New",
    "pseudocode": "## Approach\n\nUse two pointers...",
    "media": [],
    "tags": ["sorted-array"],
    "nextReview": "2026-02-25",
}

PROBLEM_2 = {
    "id": "15",
    "title": "3Sum",
    "leetcodeUrl": "https://leetcode.com/problems/3sum/",
    "difficulty": "Medium",
    "status": "New",
    "pseudocode": "## Approach\n\nSort + two pointers...",
    "media": [],
}

VALID_MODULE = {
    "slug": "two-pointers",
    "title": "Two Pointers",
    "description": "Master the two-pointer technique.",
    "content": "# Two Pointers\n\nCore concept here.",
    "order": 1,
    "media": [],
    "problems": [PROBLEM_1],
}

MODULE_NO_PROBLEMS = {
    **VALID_MODULE,
    "slug": "sliding-window",
    "title": "Sliding Window",
    "problems": [],
}


# ── POST /api/playbook ──────────────────────────────────────────────────────────

class TestCreateModule:
    def test_create_returns_201(self, client: TestClient):
        r = client.post("/api/playbook", json=VALID_MODULE, headers=auth_headers())
        assert r.status_code == 201
        assert r.json()["slug"] == "two-pointers"

    def test_create_without_problems(self, client: TestClient):
        r = client.post("/api/playbook", json=MODULE_NO_PROBLEMS, headers=auth_headers())
        assert r.status_code == 201

    def test_create_with_multiple_problems(self, client: TestClient):
        module = {**VALID_MODULE, "problems": [PROBLEM_1, PROBLEM_2]}
        r = client.post("/api/playbook", json=module, headers=auth_headers())
        assert r.status_code == 201

    def test_duplicate_slug_returns_409(self, client: TestClient):
        client.post("/api/playbook", json=VALID_MODULE, headers=auth_headers())
        r = client.post("/api/playbook", json=VALID_MODULE, headers=auth_headers())
        assert r.status_code == 409

    def test_missing_required_field_returns_422(self, client: TestClient):
        bad = {k: v for k, v in VALID_MODULE.items() if k != "title"}
        r = client.post("/api/playbook", json=bad, headers=auth_headers())
        assert r.status_code == 422

    def test_unauthenticated_returns_401(self, client: TestClient):
        r = client.post("/api/playbook", json=VALID_MODULE)
        assert r.status_code == 401


# ── PUT /api/playbook/{slug} ────────────────────────────────────────────────────

class TestUpdateModule:
    def _seed(self, client: TestClient, module: dict = VALID_MODULE) -> None:
        client.post("/api/playbook", json=module, headers=auth_headers())

    def test_update_title(self, client: TestClient):
        self._seed(client)
        r = client.put(
            "/api/playbook/two-pointers",
            json={"title": "Two Pointers (Updated)"},
            headers=auth_headers(),
        )
        assert r.status_code == 200

    def test_update_description_and_order(self, client: TestClient):
        self._seed(client)
        r = client.put(
            "/api/playbook/two-pointers",
            json={"description": "New description", "order": 2},
            headers=auth_headers(),
        )
        assert r.status_code == 200

    def test_update_nonexistent_returns_404(self, client: TestClient):
        r = client.put(
            "/api/playbook/does-not-exist",
            json={"title": "X"},
            headers=auth_headers(),
        )
        assert r.status_code == 404

    def test_upsert_new_problem(self, client: TestClient):
        self._seed(client)
        r = client.put(
            "/api/playbook/two-pointers",
            json={"upsert_problems": [PROBLEM_2]},
            headers=auth_headers(),
        )
        assert r.status_code == 200

    def test_upsert_existing_problem_overwrites(self, client: TestClient):
        self._seed(client)
        updated_problem = {**PROBLEM_1, "status": "Review", "nextReview": "2026-03-01"}
        r = client.put(
            "/api/playbook/two-pointers",
            json={"upsert_problems": [updated_problem]},
            headers=auth_headers(),
        )
        assert r.status_code == 200

    def test_delete_problem(self, client: TestClient):
        self._seed(client)
        r = client.put(
            "/api/playbook/two-pointers",
            json={"delete_problem_ids": ["167"]},
            headers=auth_headers(),
        )
        assert r.status_code == 200

    def test_delete_nonexistent_problem_is_noop(self, client: TestClient):
        """Deleting a problem id that doesn't exist should not error."""
        self._seed(client)
        r = client.put(
            "/api/playbook/two-pointers",
            json={"delete_problem_ids": ["9999"]},
            headers=auth_headers(),
        )
        assert r.status_code == 200

    def test_simultaneous_upsert_and_delete(self, client: TestClient):
        self._seed(client)
        r = client.put(
            "/api/playbook/two-pointers",
            json={
                "upsert_problems": [PROBLEM_2],
                "delete_problem_ids": ["167"],
            },
            headers=auth_headers(),
        )
        assert r.status_code == 200

    def test_no_fields_still_returns_200(self, client: TestClient):
        """Empty update body with no module fields and no problem ops is a no-op."""
        self._seed(client)
        r = client.put("/api/playbook/two-pointers", json={}, headers=auth_headers())
        assert r.status_code == 200


# ── DELETE /api/playbook/{slug} ─────────────────────────────────────────────────

class TestDeleteModule:
    def test_delete_returns_200(self, client: TestClient):
        client.post("/api/playbook", json=VALID_MODULE, headers=auth_headers())
        r = client.delete("/api/playbook/two-pointers", headers=auth_headers())
        assert r.status_code == 200
        assert r.json()["message"] == "Module deleted"

    def test_delete_nonexistent_returns_404(self, client: TestClient):
        r = client.delete("/api/playbook/does-not-exist", headers=auth_headers())
        assert r.status_code == 404

    def test_delete_removes_all_problems(self, client: TestClient):
        """After delete, a re-create of the same slug should succeed (no leftovers)."""
        module = {**VALID_MODULE, "problems": [PROBLEM_1, PROBLEM_2]}
        client.post("/api/playbook", json=module, headers=auth_headers())
        client.delete("/api/playbook/two-pointers", headers=auth_headers())
        # Re-create should not 409
        r = client.post("/api/playbook", json=VALID_MODULE, headers=auth_headers())
        assert r.status_code == 201

    def test_double_delete_returns_404(self, client: TestClient):
        client.post("/api/playbook", json=VALID_MODULE, headers=auth_headers())
        client.delete("/api/playbook/two-pointers", headers=auth_headers())
        r = client.delete("/api/playbook/two-pointers", headers=auth_headers())
        assert r.status_code == 404

    def test_delete_module_without_problems(self, client: TestClient):
        client.post("/api/playbook", json=MODULE_NO_PROBLEMS, headers=auth_headers())
        r = client.delete("/api/playbook/sliding-window", headers=auth_headers())
        assert r.status_code == 200

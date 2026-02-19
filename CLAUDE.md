# blog-backend — Claude Code Context

> Backend API for [botthef.xyz](https://www.botthef.xyz). Admin-only write API — reads are handled directly by the Next.js frontend via AWS SDK.

- **Remote:** https://github.com/utkshriv/blog-backend.git
- **Branch:** `main`

---

## Tech Stack

- **Python 3.12** — Lambda runtime
- **FastAPI** — routing, validation, Swagger docs at `/docs`
- **Mangum** — ASGI adapter (same FastAPI app runs locally and on Lambda)
- **Pydantic** — request/response models (bundled with FastAPI)
- **boto3** — AWS SDK for DynamoDB and S3
- **uv** — package manager (`pyproject.toml`, lockfile, dev/prod dependency groups)

---

## Project Structure

```
blog-backend/
├── src/
│   ├── admin/                     ← Admin Lambda (write operations only)
│   │   ├── handler.py             ← Lambda entry (Mangum wraps FastAPI app)
│   │   └── routes/
│   │       ├── blog.py            ← POST/PUT/DELETE /api/blog
│   │       ├── playbook.py        ← POST/PUT/DELETE /api/playbook
│   │       └── upload.py          ← POST /api/upload-url
│   │
│   └── shared/                    ← Shared utilities (all routes import from here)
│       ├── db.py                  ← DynamoDB client + query helpers
│       ├── s3.py                  ← S3 client + pre-signed URL generation
│       ├── models.py              ← Pydantic models (Post, Module, Problem, Media)
│       ├── config.py              ← Env vars, table names, bucket name, endpoints
│       └── auth.py                ← JWT token validation
│
├── tests/
│   ├── test_blog.py
│   ├── test_playbook.py
│   ├── test_integration.py        ← Integration tests (httpx + DynamoDB Local)
│   └── conftest.py                ← Fixtures, moto mock setup
│
├── scripts/
│   └── integration_test.sh        ← One-command integration test runner
│
├── pyproject.toml
├── uv.lock
└── README.md
```

---

## API Routes

All routes require a valid admin JWT (`Depends(verify_admin_token)`).

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/api/blog` | Create a new blog post |
| PUT | `/api/blog/{slug}` | Update an existing blog post |
| DELETE | `/api/blog/{slug}` | Delete a blog post (+ its S3 media) |
| POST | `/api/playbook` | Create a new playbook module |
| PUT | `/api/playbook/{slug}` | Update a module |
| DELETE | `/api/playbook/{slug}` | Delete a module (+ its S3 media) |
| POST | `/api/upload-url` | Generate a pre-signed S3 PUT URL for image upload |

> **No public GET routes.** The Next.js frontend reads DynamoDB directly via `AwsContentService`.

---

## Auth

- The frontend (NextAuth.js) sends a JWT/session token in the `Authorization` header.
- `shared/auth.py` validates the token on every request — only the whitelisted admin email passes.
- All 7 routes are protected via `Depends(verify_admin_token)`.

---

## Data Models (`shared/models.py`)

```python
Post     { slug, title, date, excerpt, tags[], content (MDX), media[], createdAt, updatedAt }
Module   { slug, title, description, content (MDX), order, media[], createdAt, updatedAt }
Problem  { id, title, leetcodeUrl, difficulty, status, pseudocode, media[], tags[]?,
           lastSolved?, nextReview?, createdAt, updatedAt }
Media    { key, s3Key, type }   # key = relative name in MDX, s3Key = full S3 path
```

---

## DynamoDB Tables

### `blog` table
- **PK:** `BLOG#<slug>` | **SK:** `METADATA`
- Key attributes: `title`, `date`, `excerpt`, `tags`, `content` (full MDX), `media[]`, `createdAt`, `updatedAt`
- **GSI `date-index`:** GSI PK = `SK` ("METADATA"), GSI SK = `date` — sorted post listing without scan

### `playbook` table
- Module item: **PK:** `PLAYBOOK#<slug>` | **SK:** `METADATA`
- Problem item: **PK:** `PLAYBOOK#<slug>` | **SK:** `PROBLEM#<id>`
- **GSI `status-review-index`:** PK = `status`, SK = `nextReview` — cross-module review queue
- **GSI `playbook-collection-gsi`:** PK = `collection` ("PLAYBOOK"), SK = `PK` — fetch all modules in one query

---

## S3 Integration

- **Image uploads:** Browser PUTs directly to S3 via pre-signed URL (image bytes never pass through Lambda).
  - `POST /api/upload-url` → Lambda generates pre-signed PUT URL (5 min expiry) → client uploads directly.
- **Image reads:** S3 bucket has public `GetObject` on `images/*` — browser loads images directly.
- **Deletes:** Backend reads `media[]` array, deletes each `s3Key` from S3, then deletes DynamoDB item(s).

S3 key structure: `images/blog/<slug>/<file>` and `images/playbook/<slug>/problems/<id>/<file>`

---

## Local Testing

### 1. Install dependencies

```bash
uv sync --all-groups
```

### 2. Create `.env.local`

```env
ENV=local
AWS_ACCESS_KEY_ID=dummy
AWS_SECRET_ACCESS_KEY=dummy
AWS_REGION=us-west-2
DYNAMODB_BLOG_TABLE=blog
DYNAMODB_PLAYBOOK_TABLE=playbook
S3_BUCKET=botthef-content-bucket
DYNAMODB_ENDPOINT=http://localhost:8002
ADMIN_EMAIL=your@email.com
NEXTAUTH_SECRET=a-secret-at-least-32-characters-long
```

### 3. Start DynamoDB Local (Docker)

```bash
docker compose up -d
```

> **Note:** `--no-sign-request` does **not** work with this version of DynamoDB Local (v3.3.0). Always prefix `aws dynamodb` commands with `AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy`. DynamoDB Local accepts any credentials — it just requires a signed request.

### 4. Create tables in DynamoDB Local

Run once per container lifecycle (tables are lost on container restart — DynamoDB Local runs `-inMemory`).

```bash
# blog table
AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy \
aws dynamodb create-table \
  --endpoint-url http://localhost:8002 \
  --table-name blog \
  --attribute-definitions \
      AttributeName=PK,AttributeType=S \
      AttributeName=SK,AttributeType=S \
      AttributeName=date,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[
    {"IndexName":"date-index",
     "KeySchema":[{"AttributeName":"SK","KeyType":"HASH"},{"AttributeName":"date","KeyType":"RANGE"}],
     "Projection":{"ProjectionType":"ALL"}}
  ]' \
  --region us-west-2

# playbook table
AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy \
aws dynamodb create-table \
  --endpoint-url http://localhost:8002 \
  --table-name playbook \
  --attribute-definitions \
      AttributeName=PK,AttributeType=S \
      AttributeName=SK,AttributeType=S \
      AttributeName=status,AttributeType=S \
      AttributeName=nextReview,AttributeType=S \
      AttributeName=collection,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[
    {"IndexName":"status-review-index",
     "KeySchema":[{"AttributeName":"status","KeyType":"HASH"},{"AttributeName":"nextReview","KeyType":"RANGE"}],
     "Projection":{"ProjectionType":"ALL"}},
    {"IndexName":"playbook-collection-gsi",
     "KeySchema":[{"AttributeName":"collection","KeyType":"HASH"},{"AttributeName":"PK","KeyType":"RANGE"}],
     "Projection":{"ProjectionType":"ALL"}}
  ]' \
  --region us-west-2
```

### 5. Start the dev server

Use `source` (not `xargs`) to load env vars — `xargs` does not reliably export vars to background processes:

```bash
source .env.local && PYTHONPATH=src uv run uvicorn admin.handler:app --reload --port 8001
```

Swagger UI: http://localhost:8001/docs

### 6. Generate a test JWT

The `/docs` UI requires a Bearer token. Generate one with Python:

```python
# run: PYTHONPATH=src uv run python -c "$(cat below)"
from jose import jwt
from datetime import datetime, timezone, timedelta

token = jwt.encode(
    {"email": "your@email.com", "exp": datetime.now(timezone.utc) + timedelta(hours=8)},
    "a-secret-at-least-32-characters-long",
    algorithm="HS256",
)
print(token)
```

Paste the token into the Swagger **Authorize** dialog as: `Bearer <token>`

### 7. Run unit tests (no Docker needed — moto mocks AWS)

```bash
uv run pytest tests/ -v
```

---

## Environment Variables

```env
ENV=local                          # "local" uses DYNAMODB_ENDPOINT; anything else = real AWS
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
AWS_REGION=us-west-2
DYNAMODB_BLOG_TABLE=blog
DYNAMODB_PLAYBOOK_TABLE=playbook
S3_BUCKET=botthef-content-bucket
DYNAMODB_ENDPOINT=http://localhost:8002   # local only
ADMIN_EMAIL=<whitelisted-email>
NEXTAUTH_SECRET=<same-secret-used-by-nextauth>
```

---

## Deployment

### Primary: CDK bundling (recommended)

`blog-infra/lib/backend-stack.ts` uses `lambda.Code.fromAsset()` with Docker bundling. Running `cdk deploy` from `blog-infra/` packages this repo automatically — no manual steps needed.

```bash
# from blog-infra/
npx cdk deploy BackendStack
```

Prerequisites before the first deploy:
1. AWS CLI configured (`aws configure`)
2. CDK bootstrapped (`cdk bootstrap aws://ACCOUNT_ID/us-west-2`)
3. SSM parameters created:
   ```bash
   aws ssm put-parameter --name /botthef/admin-email   --value "you@email.com"          --type String --region us-west-2
   aws ssm put-parameter --name /botthef/nextauth-secret --value "your-nextauth-secret" --type String --region us-west-2
   ```

### Manual: standalone ZIP (hotfixes / CI)

Use `scripts/build_lambda.sh` to build a deployable ZIP without CDK:

```bash
./scripts/build_lambda.sh
# → lambda.zip

aws lambda update-function-code \
  --function-name botthef-admin-api \
  --zip-file fileb://lambda.zip \
  --region us-west-2
```

The Lambda handler path is `admin.handler.handler`.

---

## Integration Testing (Pre-Deployment E2E)

> Run these before every Lambda deploy. Unlike unit tests (moto, in-process), integration tests hit a **live FastAPI server** over real HTTP and persist data to **DynamoDB Local** — catching serialisation bugs, auth header edge cases, and DynamoDB expression issues that moto can miss.

### Unit tests vs Integration tests

| Layer | Unit tests (`pytest` + moto) | Integration tests (`pytest` + live server) |
|-------|------------------------------|---------------------------------------------|
| Transport | `TestClient` (in-process, no TCP) | Real HTTP via `httpx` |
| DynamoDB | Mocked by moto | DynamoDB Local (Docker) |
| S3 | Mocked by moto | Pre-signed URL generated locally (no real upload needed) |
| Speed | ~2 s | ~15–30 s |
| When to run | Every code change | Before every Lambda deploy |

### Automated runner (recommended)

`scripts/integration_test.sh` handles everything in one command — no manual steps needed:

```bash
./scripts/integration_test.sh
```

What it does automatically:
1. Loads `.env.local`
2. Starts DynamoDB Local via `docker compose up -d` (skips if already running)
3. Waits for DynamoDB Local to be healthy
4. Creates both tables idempotently (skips if they already exist)
5. Starts the FastAPI server in the background and waits for `/health`
6. Runs `pytest tests/test_integration.py -v`
7. Kills the server on exit (success or failure)

Pass extra pytest args through:

```bash
./scripts/integration_test.sh -k blog       # run only blog tests
./scripts/integration_test.sh -x            # stop on first failure
```

---

### Manual steps (reference only)

#### Step 1 — Start DynamoDB Local

```bash
docker compose up -d
```

Starts `amazon/dynamodb-local` on `localhost:8002` (in-memory, data lost on container stop).

#### Step 2 — Create DynamoDB tables

> **Important:** `--no-sign-request` does not work with DynamoDB Local v3.3.0. Prefix with dummy credentials instead.

```bash
# blog table
AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy \
aws dynamodb create-table \
  --endpoint-url http://localhost:8002 \
  --table-name blog \
  --attribute-definitions \
      AttributeName=PK,AttributeType=S \
      AttributeName=SK,AttributeType=S \
      AttributeName=date,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[
    {"IndexName":"date-index",
     "KeySchema":[{"AttributeName":"SK","KeyType":"HASH"},{"AttributeName":"date","KeyType":"RANGE"}],
     "Projection":{"ProjectionType":"ALL"}}
  ]' \
  --region us-west-2

# playbook table
AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy \
aws dynamodb create-table \
  --endpoint-url http://localhost:8002 \
  --table-name playbook \
  --attribute-definitions \
      AttributeName=PK,AttributeType=S \
      AttributeName=SK,AttributeType=S \
      AttributeName=status,AttributeType=S \
      AttributeName=nextReview,AttributeType=S \
      AttributeName=collection,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[
    {"IndexName":"status-review-index",
     "KeySchema":[{"AttributeName":"status","KeyType":"HASH"},{"AttributeName":"nextReview","KeyType":"RANGE"}],
     "Projection":{"ProjectionType":"ALL"}},
    {"IndexName":"playbook-collection-gsi",
     "KeySchema":[{"AttributeName":"collection","KeyType":"HASH"},{"AttributeName":"PK","KeyType":"RANGE"}],
     "Projection":{"ProjectionType":"ALL"}}
  ]' \
  --region us-west-2
```

#### Step 3 — Create `.env.local` (if not already present)

```env
ENV=local
AWS_ACCESS_KEY_ID=dummy
AWS_SECRET_ACCESS_KEY=dummy
AWS_REGION=us-west-2
DYNAMODB_BLOG_TABLE=blog
DYNAMODB_PLAYBOOK_TABLE=playbook
S3_BUCKET=botthef-content-bucket
DYNAMODB_ENDPOINT=http://localhost:8002
ADMIN_EMAIL=your@email.com
NEXTAUTH_SECRET=a-secret-at-least-32-characters-long
```

#### Step 4 — Start the API server

Use `source` (not `xargs`) to load env vars reliably:

```bash
source .env.local && PYTHONPATH=src uv run uvicorn admin.handler:app --reload --port 8001
```

Verify: `curl http://localhost:8001/health` → `{"status":"ok"}`

#### Step 5 — Run integration tests

```bash
PYTHONPATH=src uv run pytest tests/test_integration.py -v
```

The test file covers:

| Class | What is tested |
|-------|----------------|
| `test_health` | Server reachable, `/health` returns 200 |
| `TestAuth` | Missing / bad / expired token → 401; wrong email → 403 |
| `TestBlogCRUD` | Full create → DynamoDB verify → update → verify → delete → verify lifecycle |
| `TestPlaybookCRUD` | Module create + initial problems; problem upsert/overwrite/delete; full module delete clears all problems |
| `TestUploadUrl` | Pre-signed URL shape for blog and playbook/problem paths; invalid content-type → 400; invalid entity-type → 400 |

All tests clean up after themselves. Running them multiple times is safe.

### Step 6 — Manual smoke tests with curl (optional)

Generate a token first:

```bash
TOKEN=$(PYTHONPATH=src uv run python -c "
from jose import jwt
from datetime import datetime, timezone, timedelta
import os
token = jwt.encode(
    {'email': os.environ['ADMIN_EMAIL'], 'exp': datetime.now(timezone.utc) + timedelta(hours=8)},
    os.environ['NEXTAUTH_SECRET'], algorithm='HS256',
)
print(token)
")
```

**Blog**

```bash
# Create
curl -s -X POST http://localhost:8001/api/blog \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"slug":"smoke-test","title":"Smoke","date":"2026-02-18","excerpt":"e","tags":[],"content":"# Hi"}' | jq

# Update
curl -s -X PUT http://localhost:8001/api/blog/smoke-test \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Smoke Updated"}' | jq

# Delete
curl -s -X DELETE http://localhost:8001/api/blog/smoke-test \
  -H "Authorization: Bearer $TOKEN" | jq
```

**Playbook**

```bash
# Create module
curl -s -X POST http://localhost:8001/api/playbook \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"slug":"smoke-mod","title":"Smoke Module","description":"d","content":"# x","order":1,"problems":[]}' | jq

# Add problem via update
curl -s -X PUT http://localhost:8001/api/playbook/smoke-mod \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"upsert_problems":[{"id":"p1","title":"P1","leetcodeUrl":"https://leetcode.com/problems/two-sum/","difficulty":"Easy","status":"New","pseudocode":"brute force"}]}' | jq

# Delete module
curl -s -X DELETE http://localhost:8001/api/playbook/smoke-mod \
  -H "Authorization: Bearer $TOKEN" | jq
```

**Upload URL**

```bash
curl -s -X POST http://localhost:8001/api/upload-url \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filename":"hero.jpg","content_type":"image/jpeg","entity_type":"blog","entity_slug":"smoke-test"}' | jq
```

### Step 7 — Inspect DynamoDB directly (optional)

> Remember: prefix all `aws dynamodb` commands with `AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy` — `--no-sign-request` does not work with DynamoDB Local v3.3.0.

List all items in a table:

```bash
AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy \
aws dynamodb scan \
  --endpoint-url http://localhost:8002 \
  --table-name blog \
  --region us-west-2 | jq '.Items'
```

Fetch a specific item:

```bash
AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy \
aws dynamodb get-item \
  --endpoint-url http://localhost:8002 \
  --table-name blog \
  --key '{"PK":{"S":"BLOG#smoke-test"},"SK":{"S":"METADATA"}}' \
  --region us-west-2 | jq '.Item'
```

### Pre-Deployment Checklist

Run through all of these before `aws lambda update-function-code`:

- [ ] `uv run pytest tests/ -v` — all unit tests pass (no Docker needed)
- [ ] `./scripts/integration_test.sh` — all 38 integration tests pass
- [ ] Manual smoke: create + update + delete a blog post via curl
- [ ] Manual smoke: create + update + delete a playbook module via curl
- [ ] Upload URL endpoint returns a well-formed pre-signed URL
- [ ] Auth: unauthenticated request returns 401; wrong email returns 403
- [ ] `docker compose down` (cleanup)

---

## Current Status

- ✅ All 7 admin routes implemented (blog CRUD, playbook CRUD, upload URL)
- ✅ JWT auth via `shared/auth.py` — HS256 signed with `NEXTAUTH_SECRET`
- ✅ DynamoDB writes follow the key design from `blog-infra` (BLOG#, PLAYBOOK#, PROBLEM#)
- ✅ S3 pre-signed URL generation + batch delete on post/module removal
- ✅ Unit tests passing (pytest + moto, no AWS account needed)
- ✅ 38/38 integration tests passing (pytest + httpx + DynamoDB Local)
- ✅ `docker-compose.yml` for one-command DynamoDB Local setup
- ✅ `scripts/integration_test.sh` — fully automated integration test runner
- ✅ `scripts/build_lambda.sh` — standalone Lambda ZIP builder for manual deploys
- ✅ Wired into `blog-infra` CDK — `cdk deploy` packages and deploys this code automatically
- ❌ Not yet deployed to AWS (CDK deploy pending — AWS account + SSM params required)

## Known Quirks

- **DynamoDB Local v3.3.0 + `--no-sign-request`:** This flag silently fails — DynamoDB Local still returns `MissingAuthenticationToken`. Always use `AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy` as a prefix instead.
- **`conftest.py` env var precedence:** `tests/conftest.py` uses `os.environ.setdefault()` so externally-passed env vars take precedence over unit-test defaults. This allows integration tests to run with real `.env.local` values while unit tests continue to use moto-safe defaults.
- **`source` vs `xargs` for env loading:** Use `source .env.local` to load env vars for the dev server. `$(cat .env.local | xargs)` does not reliably pass vars to background processes.

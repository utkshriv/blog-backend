"""
Admin Lambda entry point.

Local dev:
    PYTHONPATH=src uv run uvicorn admin.handler:app --reload --port 8001

Lambda handler (set in CDK BackendStack):
    admin.handler.handler
"""

from fastapi import FastAPI
from mangum import Mangum

from admin.routes import blog, playbook, upload

app = FastAPI(
    title="botthef Admin API",
    description="Write-only API for botthef.xyz blog and playbook content. All routes require a valid admin JWT.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(blog.router)
app.include_router(playbook.router)
app.include_router(upload.router)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


# Mangum adapts the FastAPI ASGI app for AWS Lambda + API Gateway (HTTP API).
handler = Mangum(app, lifespan="off")

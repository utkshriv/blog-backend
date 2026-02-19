import os

ENV = os.getenv("ENV", "production")
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")

BLOG_TABLE = os.getenv("DYNAMODB_BLOG_TABLE", "blog")
PLAYBOOK_TABLE = os.getenv("DYNAMODB_PLAYBOOK_TABLE", "playbook")
S3_BUCKET = os.getenv("S3_BUCKET", "botthef-content-bucket")

DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT")  # local only (http://localhost:8002)

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
NEXTAUTH_SECRET = os.getenv("NEXTAUTH_SECRET", "")

# Injected into boto3 calls when running locally
DYNAMODB_KWARGS: dict = {}
if ENV == "local" and DYNAMODB_ENDPOINT:
    DYNAMODB_KWARGS["endpoint_url"] = DYNAMODB_ENDPOINT

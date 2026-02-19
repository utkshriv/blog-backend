"""Admin route for generating pre-signed S3 upload URLs — POST /api/upload-url.

Flow:
  1. Admin UI calls POST /api/upload-url with filename, content_type, entity info.
  2. Lambda returns a pre-signed PUT URL + the S3 key.
  3. Browser uploads the file directly to S3 (Lambda never sees image bytes).
  4. Admin UI includes {key, s3Key, type} in the media[] array when saving the post/module.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from shared.auth import verify_admin_token
from shared.models import UploadUrlRequest, UploadUrlResponse
from shared.s3 import build_s3_key, generate_presigned_upload_url

router = APIRouter()

_ALLOWED_ENTITY_TYPES = {"blog", "playbook"}
_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}


@router.post("/api/upload-url", response_model=UploadUrlResponse)
def get_upload_url(req: UploadUrlRequest, _: str = Depends(verify_admin_token)):
    if req.entity_type not in _ALLOWED_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"entity_type must be one of {_ALLOWED_ENTITY_TYPES}",
        )

    if req.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"content_type must be one of {_ALLOWED_CONTENT_TYPES}",
        )

    s3_key = build_s3_key(
        entity_type=req.entity_type,
        entity_slug=req.entity_slug,
        filename=req.filename,
        problem_id=req.problem_id,
    )

    url = generate_presigned_upload_url(s3_key=s3_key, content_type=req.content_type)

    return UploadUrlResponse(url=url, s3Key=s3_key, key=req.filename)

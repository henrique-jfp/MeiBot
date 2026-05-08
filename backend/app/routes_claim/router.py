import base64
from fastapi import APIRouter, Request
from .ai_routes import parse_route_sheet

router = APIRouter(prefix="/routes-claim")


@router.post("/parse")
async def parse_routes(request: Request):
    data = await request.json()
    content_base64 = data.get("content_base64")
    mime_type = data.get("mime_type")

    if not content_base64 or not mime_type:
        return {"error": "missing_payload"}

    try:
        file_bytes = base64.b64decode(content_base64)
    except Exception:
        return {"error": "invalid_base64"}

    try:
        parsed = parse_route_sheet(file_bytes, mime_type)
        return parsed
    except Exception as exc:
        return {"error": "parse_failed", "detail": str(exc)}

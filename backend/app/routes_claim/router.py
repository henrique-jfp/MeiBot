import base64
import traceback
from fastapi import APIRouter, Request
from .ai_routes import PARSER_VERSION, VISION_STATUS, parse_route_sheet

router = APIRouter(prefix="/routes-claim")


@router.get("/version")
async def parser_version():
    return {
        "parser_version": PARSER_VERSION,
        "vision_available": VISION_STATUS["available"],
        "vision_reason": VISION_STATUS["reason"],
    }


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
        print(
            "[ROUTE-CLAIM] parse result "
            f"mime={mime_type} bytes={len(file_bytes)} "
            f"source={parsed.get('source')} "
            f"confidence={parsed.get('confidence')} "
            f"routes={len(parsed.get('routes') or [])} "
            f"parser_version={parsed.get('parser_version')} "
            f"vision_available={parsed.get('vision_available')} "
            f"vision_reason={parsed.get('vision_reason')} "
            f"ocr_text_len={parsed.get('ocr_text_len')} "
            f"ocr_rows={parsed.get('ocr_rows')} "
            f"error={parsed.get('error')} "
            f"error_detail={parsed.get('error_detail')}"
        )
        return parsed
    except Exception as exc:
        print(f"[ROUTE-CLAIM] parse exception mime={mime_type} bytes={len(file_bytes)} error={exc}")
        traceback.print_exc()
        return {"error": "parse_failed", "detail": str(exc)}

import io
import json
import os
import re
import unicodedata

import google.generativeai as genai
from dotenv import load_dotenv

try:
    from google.cloud import vision
    from google.oauth2 import service_account
except Exception as exc:
    print(f"[ROUTE-CLAIM] Google Vision imports unavailable: {exc}")
    vision = None
    service_account = None

try:
    from pdf2image import convert_from_bytes
    from PIL import Image
    PDF_SUPPORT_AVAILABLE = True
except ImportError:
    print("[ROUTE-CLAIM] pdf2image or Pillow not installed. PDF support will be disabled.")
    PDF_SUPPORT_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    print("[ROUTE-CLAIM] pdfplumber not installed.")
    PDFPLUMBER_AVAILABLE = False

load_dotenv()

TARGET_ALIASES = ("rocinha", "roc")
MIN_DETERMINISTIC_CONFIDENCE = 0.75
IMAGE_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
PARSER_VERSION = "routes-claim-2026-05-10-pdfplumber-v1"
ROUTES_ENABLE_GEMINI_OCR_FALLBACK = os.getenv("ROUTES_ENABLE_GEMINI_OCR_FALLBACK", "false").lower() == "true"
ROUTES_ENABLE_GEMINI_IMAGE_FALLBACK = os.getenv("ROUTES_ENABLE_GEMINI_IMAGE_FALLBACK", "false").lower() == "true"
VISION_STATUS = {
    "available": False,
    "reason": "not_initialized",
}

_genai_key = os.getenv("GEMINI_API_KEY")
if _genai_key:
    genai.configure(api_key=_genai_key)

_gemini_model_names = [
    name.strip()
    for name in os.getenv("ROUTES_GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash").split(",")
    if name.strip() and "1.5" not in name.strip()
]


def _build_vision_client():
    if vision is None or service_account is None:
        VISION_STATUS["reason"] = "google_cloud_vision_import_unavailable"
        return None

    creds_json = os.getenv("GOOGLE_VISION_CREDENTIALS_JSON")
    if not creds_json:
        VISION_STATUS["reason"] = "missing_GOOGLE_VISION_CREDENTIALS_JSON"
        print("[ROUTE-CLAIM] Vision unavailable: missing GOOGLE_VISION_CREDENTIALS_JSON")
        return None

    try:
        creds_dict = json.loads(creds_json)
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        client = vision.ImageAnnotatorClient(credentials=credentials)
        VISION_STATUS["available"] = True
        VISION_STATUS["reason"] = "ok"
        return client
    except Exception as exc:
        VISION_STATUS["reason"] = str(exc)
        print(f"[ROUTE-CLAIM] Vision unavailable: {exc}")
        return None


_vision_client = _build_vision_client()


def _normalize(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFD", str(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text.lower()).strip()


def _has_target(text):
    normalized = _normalize(text)
    return any(
        re.search(rf"\b{re.escape(alias)}\b", normalized)
        if len(alias) <= 3
        else alias in normalized
        for alias in TARGET_ALIASES
    )


def _parse_int(value):
    if value is None:
        return None
    match = re.search(r"\d+", str(value).replace(".", ""))
    return int(match.group(0)) if match else None


def _clean_gaiola(value):
    if not value:
        return None
    match = re.search(r"\b([A-Z])\s*[-–]?\s*(\d{1,3})([A-Z]{0,3})\b", value.upper())
    return f"{match.group(1)}-{match.group(2)}{match.group(3) or ''}" if match else None


def _route_lines(ocr_text):
    lines = []
    for raw_line in ocr_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if re.search(r"\b[A-Z]\s*[-–]?\s*\d{1,3}[A-Z]{0,3}\b", line.upper()):
            lines.append(line)
    return lines


def _route_rows_from_vision_response(response):
    words = []
    for page in response.full_text_annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    text = "".join(symbol.text for symbol in word.symbols).strip()
                    vertices = word.bounding_box.vertices
                    xs = [vertex.x for vertex in vertices]
                    ys = [vertex.y for vertex in vertices]
                    if not text or not xs or not ys:
                        continue
                    words.append(
                        {
                            "text": text,
                            "x": sum(xs) / len(xs),
                            "y": sum(ys) / len(ys),
                            "height": max(ys) - min(ys),
                        }
                    )

    if not words:
        return []

    median_height = sorted(word["height"] for word in words)[len(words) // 2]
    tolerance = max(8, median_height * 0.75)
    rows = []

    for word in sorted(words, key=lambda item: item["y"]):
        for row in rows:
            if abs(row["y"] - word["y"]) <= tolerance:
                row["words"].append(word)
                row["y"] = sum(item["y"] for item in row["words"]) / len(row["words"])
                break
        else:
            rows.append({"y": word["y"], "words": [word]})

    row_texts = []
    for row in sorted(rows, key=lambda item: item["y"]):
        ordered = sorted(row["words"], key=lambda item: item["x"])
        text = " ".join(item["text"] for item in ordered)
        if re.search(r"\b[A-Z]\s*[-–]?\s*\d{1,3}[A-Z]{0,3}\b", text.upper()):
            row_texts.append(text)

    return row_texts


def _extract_rocinha_count(line):
    normalized = _normalize(line)
    colon_matches = []
    for pattern in (r"\brocinha\b\s*[:=-]\s*(\d{1,4})", r"\broc\b\s*[:=-]\s*(\d{1,4})"):
        colon_matches.extend(re.findall(pattern, normalized))
    if colon_matches:
        return _parse_int(colon_matches[-1])

    if "dissec" in normalized:
        tail = re.split(r"dissec\w*", normalized, maxsplit=1)[-1]
        for pattern in (r"\brocinha\b\D{0,12}(\d{1,4})", r"\broc\b\D{0,12}(\d{1,4})"):
            match = re.search(pattern, tail)
            if match:
                return _parse_int(match.group(1))

    patterns = (
        r"\brocinha\b\D{0,12}(\d{1,4})",
        r"\broc\b\D{0,12}(\d{1,4})",
        r"(\d{1,4})\D{0,12}\brocinha\b",
        r"(\d{1,4})\D{0,12}\broc\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return _parse_int(match.group(1))
    return None


def _extract_total_packages(line):
    normalized = _normalize(line)
    total_patterns = (
        r"(?:total|pacotes|pct|pcts|qtd)\D{0,8}(\d{1,4})",
        r"(\d{1,4})\D{0,8}(?:pacotes|pct|pcts)",
    )
    for pattern in total_patterns:
        match = re.search(pattern, normalized)
        if match:
            return _parse_int(match.group(1))

    numbers = [_parse_int(item) for item in re.findall(r"\b\d{1,4}\b", line)]
    numbers = [item for item in numbers if item is not None]
    return max(numbers) if numbers else None


def _extract_cluster(line, gaiola):
    cleaned = line
    if gaiola:
        compact = gaiola.replace("-", r"\s*[-–]?\s*")
        cleaned = re.sub(rf"\b{compact}\b", " ", cleaned, count=1, flags=re.IGNORECASE)

    cleaned = re.sub(r"\b\d{1,4}\b", " ", cleaned, count=1)
    vehicle_split = re.split(r"\b(?:ROTA\s+MISTA|PASSEIO|MOTO)\b", cleaned, flags=re.IGNORECASE)
    cleaned = vehicle_split[0]
    pieces = re.split(r"\s{2,}|;", cleaned)
    for piece in pieces:
        piece = piece.strip(" :-")
        if piece and not re.fullmatch(r"\d+", piece):
            return piece
    return None


def _parse_routes_from_text(ocr_text, source="vision_parser"):
    return _parse_routes_from_lines(_route_lines(ocr_text), source)


def _parse_routes_from_lines(lines, source):
    routes = []
    for line in lines:
        gaiola = _clean_gaiola(line)
        if not gaiola:
            continue

        has_target = _has_target(line)
        rocinha_count = _extract_rocinha_count(line) if has_target else None
        dissecacao = {"Rocinha": rocinha_count} if rocinha_count is not None else {}
        cluster = _extract_cluster(line, gaiola)

        routes.append(
            {
                "gaiola": gaiola,
                "bairro": "Rocinha" if has_target else cluster,
                "pacotes_total": _extract_total_packages(line),
                "dissecacao": dissecacao,
            }
        )

    target_routes = [
        route
        for route in routes
        if _has_target(route.get("bairro")) or "Rocinha" in route.get("dissecacao", {})
    ]

    if target_routes and any(route.get("dissecacao") for route in target_routes):
        confidence = 0.9
    elif target_routes:
        confidence = 0.8
    elif routes:
        confidence = 0.55
    else:
        confidence = 0.0

    return {
        "routes": routes,
        "confidence": confidence,
        "source": source,
    }


def _extract_text_with_pdfplumber(file_bytes):
    if not PDFPLUMBER_AVAILABLE:
        return ""
    
    try:
        text_lines = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(layout=True)
                if page_text:
                    text_lines.append(page_text)
        return "\n".join(text_lines)
    except Exception as exc:
        print(f"[ROUTE-CLAIM] pdfplumber error: {exc}")
        return ""


def _extract_text_with_vision(file_bytes):
    if not _vision_client:
        return "", []

    image = vision.Image(content=file_bytes)
    response = _vision_client.document_text_detection(image=image)
    if response.error.message:
        VISION_STATUS["reason"] = response.error.message
        print(f"[ROUTE-CLAIM] Vision OCR error: {response.error.message}")
        return "", []

    if not response.full_text_annotation:
        return "", []

    return response.full_text_annotation.text, _route_rows_from_vision_response(response)


def _compact_ocr_for_gemini(ocr_text):
    relevant = []
    for line in ocr_text.splitlines():
        normalized = _normalize(line)
        if (
            re.search(r"\b[a-z]\s*[-–]?\s*\d{1,3}[a-z]{0,3}\b", normalized)
            or _has_target(line)
            or any(token in normalized for token in ("pacote", "total", "dissec"))
        ):
            relevant.append(line.strip())

    compact = "\n".join(line for line in relevant if line)
    return compact[:6000]


def _parse_json_response(text):
    cleaned = text.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


def _normalize_ai_routes(parsed):
    raw_routes = parsed if isinstance(parsed, list) else parsed.get("routes", [])
    routes = []

    for item in raw_routes if isinstance(raw_routes, list) else []:
        if not isinstance(item, dict):
            continue

        gaiola = _clean_gaiola(item.get("gaiola") or item.get("Gaiola") or item.get("route"))
        if not gaiola:
            continue

        dissecacao = item.get("dissecacao") or item.get("bairros") or {}
        if not isinstance(dissecacao, dict):
            dissecacao = {}

        normalized_dissecacao = {}
        for key, value in dissecacao.items():
            if _has_target(key):
                normalized_dissecacao["Rocinha"] = _parse_int(value)
            else:
                normalized_dissecacao[str(key)] = _parse_int(value)

        bairro = item.get("bairro") or item.get("cluster") or item.get("Cluster")
        if _has_target(bairro):
            bairro = "Rocinha"

        routes.append(
            {
                "gaiola": gaiola,
                "bairro": bairro,
                "pacotes_total": _parse_int(
                    item.get("pacotes_total")
                    or item.get("spr")
                    or item.get("SPR")
                    or item.get("pacotes")
                ),
                "dissecacao": normalized_dissecacao,
            }
        )

    return routes


def _confidence_for_routes(routes, source):
    target_routes = [
        route
        for route in routes
        if _has_target(route.get("bairro")) or "Rocinha" in route.get("dissecacao", {})
    ]
    if target_routes and any(route.get("dissecacao") for route in target_routes):
        return 0.9
    if target_routes:
        return 0.8
    if routes and source == "gemini_image_fallback":
        return 0.6
    if routes:
        return 0.55
    return 0.0


def _fallback_with_gemini(file_bytes, mime_type, ocr_text=""):
    if not _genai_key or not _gemini_model_names:
        return {"routes": [], "confidence": 0.0, "source": "no_gemini"}

    prompt = (
        "Voce esta lendo uma planilha de rotas em imagem. O layout tem colunas "
        "GAIOLA, SPR, CLUSTER, BAIRROS, TIPO DE VEICULO e TRANSPORTADORA. "
        "Extraia TODAS as linhas de rota visiveis. Responda somente JSON valido: "
        '{"routes":[{"gaiola":"B-41","bairro":"Rocinha","pacotes_total":124,'
        '"dissecacao":{"Rocinha":57,"Gavea":30}}]}. '
        "Regras: gaiola pode ter sufixo como G-48NS; SPR e o total de pacotes; "
        "CLUSTER vira bairro; BAIRROS contem a dissecacao por bairro. "
        "Se BAIRROS tiver 'Rocinha: 5', coloque dissecacao.Rocinha=5, mesmo que "
        "antes apareca 'Gavea: 93'. Se CLUSTER for Rocinha, bairro='Rocinha'. "
        "Use null quando faltar numero e {} quando nao houver dissecacao. "
        "Nao explique, nao use markdown."
    )

    source = "gemini_ocr_fallback" if ocr_text else "gemini_image_fallback"
    last_error = None
    for model_name in _gemini_model_names:
        try:
            model = genai.GenerativeModel(model_name)
            if ocr_text:
                response = model.generate_content(
                    [prompt, "OCR text:\n" + _compact_ocr_for_gemini(ocr_text)],
                    generation_config={"response_mime_type": "application/json"},
                )
            else:
                response = model.generate_content(
                    [prompt, {"mime_type": mime_type, "data": file_bytes}],
                    generation_config={"response_mime_type": "application/json"},
                )

            parsed = _parse_json_response(response.text)
            routes = _normalize_ai_routes(parsed)
            return {
                "routes": routes,
                "confidence": _confidence_for_routes(routes, source),
                "source": f"{source}:{model_name}",
            }
        except Exception as exc:
            last_error = exc
            print(f"[ROUTE-CLAIM] Gemini fallback failed model={model_name}: {exc}")

    return {
        "routes": [],
        "confidence": 0.0,
        "source": "gemini_fallback_failed",
        "error_detail": str(last_error) if last_error else None,
    }


def parse_route_sheet(file_bytes: bytes, mime_type: str):
    ocr_text = ""
    ocr_rows = []

    # Fluxo Prioritário para PDF: pdfplumber (Direto no texto)
    if mime_type == "application/pdf" and PDFPLUMBER_AVAILABLE:
        pdf_text = _extract_text_with_pdfplumber(file_bytes)
        if pdf_text:
            pdf_parsed = _parse_routes_from_text(pdf_text, source="pdfplumber_parser")
            if pdf_parsed["confidence"] >= MIN_DETERMINISTIC_CONFIDENCE:
                pdf_parsed["parser_version"] = PARSER_VERSION
                return pdf_parsed
            print(f"[ROUTE-CLAIM] pdfplumber confidence low ({pdf_parsed['confidence']}), falling back to image/vision")

    # Fallback para PDF ou fluxo de Imagem: OCR via Google Vision
    img_bytes = file_bytes
    actual_mime = mime_type

    if mime_type == "application/pdf" and PDF_SUPPORT_AVAILABLE:
        try:
            images = convert_from_bytes(file_bytes, first_page=1, last_page=1, fmt="jpeg", dpi=300)
            if images:
                img_byte_arr = io.BytesIO()
                images[0].save(img_byte_arr, format="JPEG")
                img_bytes = img_byte_arr.getvalue()
                actual_mime = "image/jpeg"
                print("[ROUTE-CLAIM] PDF converted to JPEG (300 DPI) for Vision fallback")
        except Exception as exc:
            print(f"[ROUTE-CLAIM] PDF conversion failed: {exc}")

    deterministic = {
        "routes": [],
        "confidence": 0.0,
        "source": "unsupported",
        "parser_version": PARSER_VERSION,
        "vision_available": VISION_STATUS["available"],
        "vision_reason": VISION_STATUS["reason"],
        "ocr_text_len": 0,
        "ocr_rows": 0,
    }

    if actual_mime in IMAGE_MIME_TYPES:
        ocr_text, ocr_rows = _extract_text_with_vision(img_bytes)
        if ocr_rows:
            deterministic = _parse_routes_from_lines(ocr_rows, "vision_geometry_parser")
            deterministic["parser_version"] = PARSER_VERSION
            deterministic["vision_available"] = VISION_STATUS["available"]
            deterministic["vision_reason"] = VISION_STATUS["reason"]
            deterministic["ocr_text_len"] = len(ocr_text or "")
            deterministic["ocr_rows"] = len(ocr_rows)
            
            if deterministic["confidence"] < MIN_DETERMINISTIC_CONFIDENCE and ocr_rows:
                print(f"[ROUTE-CLAIM] Low confidence ({deterministic['confidence']}). First 3 rows: {ocr_rows[:3]}")
                if _has_target(ocr_text or ""):
                    print("[ROUTE-CLAIM] Target keyword found in raw text but not associated with routes.")

            if deterministic["confidence"] >= MIN_DETERMINISTIC_CONFIDENCE:
                return deterministic
        if ocr_text:
            deterministic = _parse_routes_from_text(ocr_text, source="vision_parser")
            deterministic["parser_version"] = PARSER_VERSION
            deterministic["vision_available"] = VISION_STATUS["available"]
            deterministic["vision_reason"] = VISION_STATUS["reason"]
            deterministic["ocr_text_len"] = len(ocr_text or "")
            deterministic["ocr_rows"] = len(ocr_rows)
            if deterministic["confidence"] >= MIN_DETERMINISTIC_CONFIDENCE:
                return deterministic

    should_use_gemini = (
        (bool(ocr_text) and ROUTES_ENABLE_GEMINI_OCR_FALLBACK) or
        (not ocr_text and ROUTES_ENABLE_GEMINI_IMAGE_FALLBACK)
    )
    if not should_use_gemini:
        deterministic["source"] = (
            f"ocr_parse_failed_gemini_disabled (source={deterministic.get('source')})"
            if ocr_text or ocr_rows
            else "no_ocr_gemini_disabled"
        )
        deterministic["ocr_text_len"] = len(ocr_text or "")
        deterministic["ocr_rows"] = len(ocr_rows)
        return deterministic

    fallback = _fallback_with_gemini(img_bytes, actual_mime, ocr_text)
    fallback["parser_version"] = PARSER_VERSION
    fallback["vision_available"] = VISION_STATUS["available"]
    fallback["vision_reason"] = VISION_STATUS["reason"]
    fallback["ocr_text_len"] = len(ocr_text or "")
    fallback["ocr_rows"] = len(ocr_rows)
    if fallback["routes"]:
        return fallback

    if fallback.get("source") == "gemini_fallback_failed":
        return fallback
    return deterministic
